"""Probe whether a Yandex AI Studio model accepts IMAGE input (is multimodal).
Sends one photo from the bake-off bundle and prints the response or the error.
  python3 catalog/yandex_vision_probe.py --model aliceai-llm-flash
"""
import argparse
import json
import sys

import requests

FOLDER = "b1gh24dah2ccub54lnfn"
URL = "https://llm.api.cloud.yandex.net/v1/chat/completions"


def env(k):
    for line in open(".env"):
        if line.startswith(k + "="):
            return line.strip().split("=", 1)[1]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="/tmp/weedid_bundle.json")
    a = ap.parse_args()
    key = env("YC_API_KEY")
    b64 = json.load(open(a.data))["subs"][0]["b64"]
    body = {
        "model": f"gpt://{FOLDER}/{a.model}/latest",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Что изображено на этом фото? Ответь одним предложением."},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
        "temperature": 0, "max_tokens": 200,
    }
    r = requests.post(URL, headers={"Authorization": f"Api-Key {key}"}, json=body, timeout=90)
    print(f"{a.model} -> HTTP {r.status_code}")
    print(r.text[:700])
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
