# Sample Interactions — Al-Bayan Phase 1 Acceptance Tests

These flows demonstrate expected bot behavior and serve as acceptance criteria for Phase 1. Each flow shows the exact Telegram message the user sends and the complete bot response.

---

## Flow 1: Simple Factual Question (Tier 1 + Tier 2)

**User**: What does Islam say about patience?

**Al-Bayan responds**:

```
Quran 2:153 — Al-Baqarah

يَا أَيُّهَا الَّذِينَ آمَنُوا اسْتَعِينُوا بِالصَّبْرِ وَالصَّلَاةِ ۚ إِنَّ اللَّهَ مَعَ الصَّابِرِينَ

"O you who have believed, seek help through patience and prayer. Indeed, Allah is with the patient."
— Sahih International

---

Tafsir — Ibn Kathir [Tier 2: Paraphrased]
Ibn Kathir explains that Allah commands the believers to seek help through patience in times of hardship and through prayer, for prayer is one of the greatest means of steadfastness. He notes that "Allah is with the patient" is a promise of special companionship — guidance, support, and protection — not mere proximity.

Tafsir — Al-Sa'di [Tier 2: Paraphrased]
Al-Sa'di explains that patience here encompasses patience in obedience to Allah, patience in abstaining from sin, and patience with the decrees of Allah. He emphasizes that combining patience with prayer is the key to overcoming every difficulty, as prayer connects the servant to his Lord and renews his strength and resolve.

---
What is one thing you can do today to practice patience?
```

**Validates**: Topic matching (patience → sabr), verse retrieval, Arabic with diacritics, dual tafsir display, tier labeling, practice off-ramp.

---

## Flow 2: Question Requiring Inference (Tier 3)

**User**: Is it okay to feel angry at God when life is hard?

**Al-Bayan responds**:

```
Quran 2:286 — Al-Baqarah

لَا يُكَلِّفُ اللَّهُ نَفْسًا إِلَّا وُسْعَهَا

"Allah does not burden a soul beyond that it can bear."
— Sahih International

Quran 94:5-6 — Ash-Sharh

فَإِنَّ مَعَ الْعُسْرِ يُسْرًا ﴿٥﴾ إِنَّ مَعَ الْعُسْرِ يُسْرًا ﴿٦﴾

"Indeed, with hardship comes ease. Indeed, with hardship comes ease."
— Sahih International

---

Tafsir — Ibn Kathir [Tier 2: Paraphrased]
On 2:286, Ibn Kathir explains that Allah in His mercy does not require of any soul more than it is able to bear. This verse was revealed as a relief to the companions who feared they would be held accountable for even their involuntary thoughts. On 94:5-6, he notes the repetition is deliberate emphasis — ease is not merely promised once but guaranteed doubly alongside every hardship.

Tafsir — Al-Sa'di [Tier 2: Paraphrased]
Al-Sa'di comments that this verse is among the greatest sources of comfort in the Quran. He explains that hardship is never absolute — it is always accompanied by ease, and the ease that follows is always greater than the hardship that preceded it. The servant should trust that Allah's wisdom is behind every trial.

---

[Tier 3: Inferred — Not reviewed by a scholar]
The Quran does not address anger at God directly, but these verses reveal a consistent theme: Allah is aware of human limitation and has promised that no burden exceeds what a soul can bear. The emphasis is not on suppressing emotion but on redirecting it — toward patience, prayer, and trust that ease accompanies hardship. Feeling overwhelmed is human. The Quranic response is not condemnation of the feeling, but an invitation to channel it toward the One who already knows what you carry.

This is an inference drawn from multiple sources. It has not been reviewed by a scholar. Please consult a qualified scholar for definitive guidance.

---
When hardship feels heavy today, what is one small act of trust you can offer?
```

**Validates**: Fuzzy topic mapping, multi-verse retrieval, Tier 2 tafsir, Tier 3 inference generation, Tier 3 disclaimer, practice off-ramp.

---

## Flow 3: Fiqh Ruling Question (Scholar Gate)

**User**: Is cryptocurrency halal?

**Al-Bayan responds**:

```
This question involves a fiqh ruling that requires qualified scholarly judgment.

I can share relevant Quranic verses and commentary about fair trade, honest dealings, and the prohibition of riba (usury) for context — but I cannot issue rulings on whether specific financial instruments are permissible.

Please consult a qualified scholar (mufti) who can evaluate the specifics of cryptocurrency in light of Islamic jurisprudence.

Would you like me to share Quranic principles on trade and financial ethics instead?
```

**Validates**: Fiqh keyword detection ("halal"), scholar gate activation, graceful redirect, offer of related contextual content.

---

## Flow 4: Question Outside Knowledge Base

**User**: What does Islam say about space travel?

**Al-Bayan responds**:

```
I don't have specific knowledge on this topic yet.

My current scope covers 10 Quranic verses across these themes: patience, gratitude, purpose of life, mercy, prayer, justice, trust in God, knowledge, hardship, and sincerity.

For questions beyond this scope, I recommend consulting a knowledgeable scholar or trusted Islamic resource.

May Allah increase us all in knowledge.
```

**Validates**: Knowledge boundary detection, honest scope disclosure, graceful limitation response.
