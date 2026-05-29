# Draft: MFWD dataset license clarification email

**To send:** to the corresponding author(s) of the MFWD paper. The paper lists
multiple authors at the Grimm Lab, TU Munich. Best primary recipient is
**Prof. Dr. Dominik Grimm** (head of lab) — the contact email is on the
[grimmlab.de](https://grimmlab.de/) site or on the article's first page.
If a co-author is listed as "corresponding author" in the article, copy them too.

**Suggested cc:** none initially.

**Subject:** MFWD dataset license clarification for commercial use

---

Dear Prof. Grimm (and co-authors),

I am the founder of Flagleaf, an early-stage Russian agritech startup
building computer-vision tools for in-field weed identification. We have
been studying your *Manually annotated and curated Dataset of diverse Weed
Species in Maize and Sorghum for Computer Vision* (Scientific Data, 2024)
and would like to use a subset of MFWD as part of a pre-annotation
("bootstrap") model that helps human annotators label our own field
photographs more efficiently.

We have noted that the article is published under CC BY, and the
`download_by_ftp.py` code is released under the MIT License. The article's
data-availability section directs readers to the GitHub repository but
does not separately state a license for the dataset itself.

Before downloading and using the data, I would like to confirm in writing
that we have your permission to:

1. Use a subset of the MFWD dataset (per-species selection via
   `download_by_ftp.py`) for training internal computer-vision models;
2. Use the resulting trained models in a commercial product, with the
   understanding that the dataset itself will not be redistributed and
   trained model weights derived from MFWD will not be released publicly;
3. Cite the MFWD paper in our internal data card and in any external
   publications that result from the work.

If a different arrangement (a written license, an attribution clause, a
contact for licensing inquiries within your institution) would be more
appropriate, I'd be happy to follow whatever process you prefer.

For context: we are working in Belgorod region (Central Black Earth zone)
on weed identification in soybean, wheat and sunflower. We are using MFWD
specifically because it has by far the most thorough manual annotation of
European broadleaf weeds (Ambrosia, Amaranthus, Chenopodium, etc.) and
covers species we cannot bootstrap from any other open dataset.

Thank you very much for the dataset — it is, in my judgment, the most
well-engineered weed-detection corpus published to date.

Best regards,

[Your full name]
Founder, Flagleaf
akhalioulline@gmail.com

---

## What to do after sending

1. **Save the sent message** in a folder `legal/mfwd-license/` in your iCloud
   or similar — this is the paper-trail evidence for Series A diligence.
2. **Set a 14-day reminder** to follow up if no response.
3. **When response arrives:**
   - **Positive:** save the reply alongside the sent message; update
     [PUBLIC_SOURCES.md item 6](PUBLIC_SOURCES.md) to "APPROVED (confirmed by author)" and remove the "provisional" qualifier.
   - **Negative or restrictive (e.g., academic-only):** delete any MFWD
     data already downloaded; revert PUBLIC_SOURCES.md item 6 to ❌ EXCLUDED;
     update [domain_shift_notes.md](domain_shift_notes.md) coverage tables
     to the 5/15 case; reconsider the email for similar phrasing on a
     different dataset.
   - **No response after 14 + 14 days:** record the non-response in
     PUBLIC_SOURCES.md as part of the paper trail; continue under the
     inferred-CC-BY position (the working presumption is defensible
     given the article's CC BY notice and the article's nature as a
     data paper).

## Optional tone-down or tone-up

- If you'd prefer it more formal (legal-counsel style), I can re-draft
  with explicit "I am writing to request a non-exclusive license to use…"
  language. The current draft is intentionally a researcher-to-researcher
  tone, which usually produces faster and more useful responses from
  academic labs.
- If you'd like to translate to German (Grimm Lab is German-language
  primary), that's a 5-minute edit and may produce a warmer response;
  most German academics will reply in English without issue, but the
  gesture is noticed.
