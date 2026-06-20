# CyberLeninka — bulk access + harvesting from another Mac

The server's datacenter IP (111.88.248.159) got anti-bot-blocked by CyberLeninka after a
burst of probes (20 Jun). The nightly crons are **paused**. We have 847 articles already
(the bot uses them). Two paths to get the full corpus, below.

---

## Part A — Request sanctioned bulk/API access (do this once)

CyberLeninka is open-science (CC BY). The clean long-term fix is to ask them for a proper
way to harvest. **Founder action:** find their contact on https://cyberleninka.ru/about
(section «Сотрудничество» / контакты — often `info@cyberleninka.ru`) and send the email below.

> **Тема:** Запрос на программный доступ к статьям (open access, CC BY) для агрономического ИИ-помощника
>
> Здравствуйте!
>
> Мы — команда Flagleaf (АО «Новая зерновая компания», Белгородская область) — разрабатываем
> цифрового ИИ-помощника для агрономов. КиберЛенинка для нас — ценнейший источник открытой
> науки, и мы хотим использовать научные статьи по агрономии и защите растений, чтобы давать
> агрономам ответы, опирающиеся на реальные публикации, **всегда со ссылкой на источник**
> (автор, название, ссылка на cyberleninka.ru) — как и требует лицензия CC BY.
>
> При попытке аккуратно собрать агрономический раздел через OAI-PMH наш серверный IP попал
> под антибот-защиту. Мы хотим делать это правильно и с уважением к вашей инфраструктуре,
> поэтому просим подсказать:
> 1. Есть ли у вас официальный API, выгрузка или партнёрская программа для программного доступа?
> 2. Если нет — какой режим обращения к OAI-PMH (частота, white-list IP) вы считаете допустимым
>    для гарвестинга подмножества по сельскохозяйственным наукам?
>
> Мы со своей стороны атрибутируем каждую статью обратной ссылкой на КиберЛенинку (это трафик
> к вам) и готовы обсудить любые условия.
>
> С уважением,
> Алексей Халиуллин · Flagleaf / АО «НЗК» · +7 967 150-2250 · ak@aonzk.ru

---

## Part B — Harvest from your other Mac (residential IP)

Your home Mac's internet IP isn't the blocked datacenter one, so it can likely reach CyberLeninka.
The plan: **harvest on the Mac → a file → upload → load into the database on the server.** The Mac
script has no project dependencies (only `requests`) and is gentle + resumable.

### 1. One-time setup on the other Mac
```bash
pip3 install requests              # the only dependency
cd ~/newgrain-bot && git pull      # get the latest scripts (or git clone the repo first)
```

### 2. PROBE — is CyberLeninka reachable from this Mac?
```bash
python3 scripts/cyberleninka_harvest_local.py --probe
```
- `✅ … можно запускать сбор` → good, continue.
- `⛔ … блокирует и этот IP` → this Mac is blocked too; try a different network (e.g. phone
  hotspot) or wait, and lean on Part A instead.

### 3. Small test, then the full run
```bash
# small test first (≈ a few minutes), check the file is sensible:
python3 scripts/cyberleninka_harvest_local.py --out ~/cyberleninka.jsonl --max 40
wc -l ~/cyberleninka.jsonl                      # how many articles collected

# full run — takes HOURS; leave the Mac awake & on power. Re-run anytime, it resumes:
python3 scripts/cyberleninka_harvest_local.py --out ~/cyberleninka.jsonl
```
⚠️ **Don't lower `--delay` or run several copies** — that's exactly what got the server IP
blocked. The default pace is deliberately slow and safe.

### 4. Upload the file to the server
```bash
scp ~/cyberleninka.jsonl newgrain@111.88.248.159:/tmp/cyberleninka.jsonl
```

### 5. Load it into the knowledge base (on the server)
```bash
ssh newgrain@111.88.248.159 'cd newgrain-bot && docker compose -f docker-compose.prod.yml \
  run --rm -T -e PYTHONPATH=/app -v /tmp/cyberleninka.jsonl:/data.jsonl bot \
  python -m catalog.load_literature_file /data.jsonl'
```
It prints `read N lines, inserted M new` (duplicates skipped — safe to re-load).

### 6. Verify the corpus grew
```bash
ssh newgrain@111.88.248.159 "cd newgrain-bot && docker compose -f docker-compose.prod.yml \
  exec -T postgres psql -U newgrain -d newgrain -tAc 'SELECT count(*) FROM agro_literature'"
```
The bot uses the corpus live — answers get richer immediately, no redeploy. Re-run steps 3–5
whenever you want to top it up (resumable on both ends).

---

*The server-side auto-harvester (`catalog/ingest_cyberleninka.py`) + its crons stay PAUSED until
the IP unblocks or Part A grants access. Re-enable by removing the `#PAUSED ` prefix in the
server crontab. See [knowledge-corpus-strategy.md](knowledge-corpus-strategy.md).*
