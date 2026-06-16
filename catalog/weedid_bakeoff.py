"""Bake-off: how well do vision LLMs identify OUR weeds from field photos?

Grades a model's species guess against the agronomist's label (ground truth) on
our real submissions, grounded with our species list (the model must pick FROM
our list). Gemini runs from the Mac via VPN (Google geo-blocks RU); Qwen-VL
(Yandex, in-RU) added separately.

Data file = {"subs":[{id,label,url}], "species":[{ru,latin}]} (see export query).

  GEMINI_API_KEY=... python3 catalog/weedid_bakeoff.py --data /tmp/weedid_data.json
  GEMINI_API_KEY=... python3 catalog/weedid_bakeoff.py --gemini-model gemini-2.5-pro
"""
import argparse
import base64
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import boto3
import requests
from botocore.client import Config


def load_env(path=".env"):
    env = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


ENV = load_env()


def s3_client():
    ep = ENV["S3_ENDPOINT"]
    ep = ep if ep.startswith("http") else "https://" + ep
    return boto3.client("s3", endpoint_url=ep, aws_access_key_id=ENV["S3_ACCESS_KEY"],
                        aws_secret_access_key=ENV["S3_SECRET_KEY"],
                        region_name=ENV.get("S3_REGION", "ru-central1"),
                        config=Config(signature_version="s3v4"))


def fetch_image(s3, url):
    p = urlparse(url)
    return s3.get_object(Bucket=p.netloc, Key=p.path.lstrip("/"))["Body"].read()


def norm(s):
    return re.sub(r"\s+", " ", (s or "").lower().replace("ё", "е")).strip()


def first_clause(s):
    """Drop trailing descriptions: 'Спорыш, или горец птичий' -> 'Спорыш'."""
    return re.split(r"[,/()]", s or "")[0].strip()


def build_canon(species):
    """norm(any name) -> canonical key (latin), for grading."""
    canon = {}
    for s in species:
        key = norm(s.get("latin")) or norm(s.get("ru"))
        if s.get("ru"):
            canon[norm(s["ru"])] = key
        if s.get("latin"):
            canon[norm(s["latin"])] = key
    return canon


def prompt_text(species):
    lst = "\n".join(f"- {s['ru']} ({s['latin']})" for s in species)
    return ("Ты агроном-эксперт по сорнякам Центрально-Чернозёмного региона России. "
            "На фото — сорняк с поля. Определи вид. Выбери НАИБОЛЕЕ вероятный вид ТОЛЬКО из "
            "списка ниже. Если на фото явно сорняк не из списка — верни \"latin\":\"not_in_list\". "
            "Ответь ТОЛЬКО JSON без пояснений: "
            '{"ru":"русское название","latin":"Latin name","confidence":0-100}.\n\n'
            "Список видов:\n" + lst)


def parse_json(txt):
    s = re.sub(r"^```(?:json)?|```$", "", (txt or "").strip(), flags=re.M).strip()
    for c in reversed(re.findall(r"\{[^{}]*\}", s)):   # prefer the LAST flat object
        try:
            return json.loads(c)
        except Exception:
            pass
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def call_gemini(img, prompt, key, model, tries=4):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {"contents": [{"parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}},
    ]}], "generationConfig": {"temperature": 0}}
    last = ""
    for i in range(tries):
        r = requests.post(url, json=body, timeout=120)
        if r.status_code == 200:
            try:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return parse_json(txt), txt.strip()
            except Exception as e:
                return None, f"parse: {e}; {r.text[:160]}"
        last = f"HTTP {r.status_code}"
        if r.status_code in (429, 500, 503):      # rate-limit / overload → back off + retry
            time.sleep(min(4 * (i + 1), 15))
            continue
        return None, f"{last}: {r.text[:160]}"
    return None, f"{last} after {tries} tries"


def call_yandex(img, prompt, key, folder, model, tries=3):
    body = {"model": f"gpt://{folder}/{model}/latest",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url":
                    {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}},
            ]}], "temperature": 0, "max_tokens": 4000}
    url = "https://llm.api.cloud.yandex.net/v1/chat/completions"
    last = ""
    for i in range(tries):
        r = requests.post(url, headers={"Authorization": f"Api-Key {key}"}, json=body, timeout=180)
        if r.status_code == 200:
            msg = r.json()["choices"][0]["message"]
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""
            guess = parse_json(content) or parse_json(reasoning)
            return guess, (content or reasoning).strip()
        last = f"HTTP {r.status_code}"
        if r.status_code in (429, 500, 503):
            time.sleep(min(4 * (i + 1), 12))
            continue
        return None, f"{last}: {r.text[:160]}"
    return None, f"{last} after {tries} tries"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/tmp/weedid_data.json")
    ap.add_argument("--provider", choices=["gemini", "yandex"], default="gemini")
    ap.add_argument("--gemini-model", default="gemini-2.5-flash")
    ap.add_argument("--yandex-model", default="qwen3.6-35b-a3b")
    ap.add_argument("--delay", type=float, default=None, help="seconds between calls")
    a = ap.parse_args()
    if a.provider == "yandex":
        key = ENV.get("YC_API_KEY")
        folder = ENV.get("YC_FOLDER_ID", "b1gh24dah2ccub54lnfn")
        model_name = a.yandex_model
        call = lambda img: call_yandex(img, prompt, key, folder, a.yandex_model)
        delay = a.delay if a.delay is not None else 1.0
    else:
        key = os.environ.get("GEMINI_API_KEY") or ENV.get("GEMINI_API_KEY")
        model_name = a.gemini_model
        call = lambda img: call_gemini(img, prompt, key, a.gemini_model)
        delay = a.delay if a.delay is not None else 5.0
    if not key:
        print("missing API key", file=sys.stderr)
        return 1
    d = json.load(open(a.data))
    subs, species = d["subs"], d["species"]
    canon = build_canon(species)
    prompt = prompt_text(species)
    # images come embedded (b64) from the self-contained bundle, else from S3
    s3 = None if all("b64" in s for s in subs) else s3_client()

    def resolve(name):
        return canon.get(norm(name))

    correct = total = 0
    fails_in_row = 0
    rows = []
    for sub in subs:
        try:
            img = base64.b64decode(sub["b64"]) if sub.get("b64") else fetch_image(s3, sub["url"])
        except Exception as e:
            print("skip img", sub["id"], e, file=sys.stderr)
            continue
        guess, raw = call(img)
        time.sleep(delay)                         # pace under rate limits
        total += 1
        label = sub["label"]
        g_ru = (guess or {}).get("ru")
        g_lat = (guess or {}).get("latin")
        lk = resolve(label) or resolve(first_clause(label))
        gk = (resolve(g_ru) or resolve(g_lat)
              or resolve(first_clause(g_ru or "")) or resolve(first_clause(g_lat or "")))
        nl = norm(first_clause(label))
        ng = norm(first_clause(g_ru or g_lat or ""))
        hit = bool((lk and gk and lk == gk) or (nl and ng and (nl == ng or nl in ng or ng in nl)))
        correct += 1 if hit else 0
        st = "OK  " if hit else "MISS"
        guess_disp = g_ru or g_lat or f"[{raw[:40]}]"
        print(f"  [{total}/{len(subs)}] {st} truth: {label[:24]:<24} guess: {guess_disp}",
              file=sys.stderr, flush=True)        # live progress, not a black box
        rows.append((st, label, guess_disp, (guess or {}).get("confidence", "—")))
        fails_in_row = fails_in_row + 1 if guess is None else 0
        if fails_in_row >= 5:
            print("\n⚠ 5 calls in a row failed — likely Gemini free-tier DAILY quota is "
                  "exhausted. Stop here; retry tomorrow or enable billing on the key.",
                  file=sys.stderr)
            break
    print(f"\n=== {model_name}: {correct}/{total} correct "
          f"({round(100 * correct / max(total, 1))}%) ===")
    for st, truth, guess, conf in rows:
        print(f"  {st} | truth: {truth:<24} | guess: {str(guess):<28} | conf {conf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
