# LinkedIn playbook: reach, comments, and SSI

Everything here is a heuristic, not a leaked algorithm. The mechanics that matter have been stable for years: the platform shows a post to a small first audience, watches dwell time and *meaningful* interactions, and expands from there. Optimise for someone stopping, reading and replying — the rest follows.

---

## 1. What SSI actually rewards

Social Selling Index is scored out of 100 across four equal pillars. Posting only touches one of them, which is why most people plateau around 60.

| Pillar | What moves it | Weekly minimum |
|---|---|---|
| Establish a professional brand | Complete profile, posts that get engagement, skills and recommendations | 1–2 substantive posts |
| Find the right people | Searches, profile views, relevant connection requests, following the right companies and people | 10–15 targeted requests with a one-line note |
| Engage with insights | **Commenting on other people's posts**, sharing with an added opinion, joining threads | 15–20 real comments (3+ sentences each) |
| Build relationships | Accepted requests, conversations in DMs, connections with senior people | 5–10 conversations |

The cheapest and most neglected lever is pillar 3. Twenty considered comments a week on posts from Python, backend and platform people will do more for both SSI and reach than a third post. Comment early on posts that are under an hour old, add something the author did not say, and never write "Great post!".

---

## 2. Before you publish

- Profile headline states what you do and for whom, not a job title. It is the only thing most readers of a viral post will see.
- Featured section contains the artefacts you want the traffic to land on.
- Banner and photo current; a post that works sends thousands of profile views.
- Turn on Creator mode if it is still available in your region, and set "Python", "Backend engineering", "Distributed systems" as your topics.

---

## 3. The post itself

**Structure**

1. **Hook — first two lines.** Mobile cuts at roughly 140–210 characters. The hook must be a complete, provocative thought on its own; never end it mid-sentence hoping for curiosity.
2. **One idea.** A post that teaches one thing outperforms a post that teaches five, unless the five are numbered and skimmable — which is exactly why the code screenshots carry numbers here.
3. **Body in short paragraphs.** One to three lines each, blank line between. Nobody reads a wall of text on a phone.
4. **A question at the end** that a busy expert can answer in one sentence from experience. "What did I miss?" is weak; "which of these would you refuse to let past review?" is answerable and mildly competitive.
5. **3–5 hashtags**, specific over generic. `#Python #Backend #SoftwareEngineering` plus one or two topical. Twenty hashtags read as spam.

**Formatting rules**

- No markdown. LinkedIn renders none of it — asterisks and backticks appear literally.
- No Unicode-bold text: screen readers make a mess of it and it suppresses searchability.
- Emoji sparingly or not at all in engineering content; the audience reads it as marketing.
- No external links in the post body. If a link is essential, put it in a comment ~30 minutes after publishing.
- Alt text on every image. It is an accessibility win and it is indexed.

**Screenshots**

Images beat plain text for engineering content because the code is the proof. Four is a comfortable number and six the practical maximum before people stop swiping — see `README.md` for the capture recipe.

**Write for the widest reader who could act on it**

Reach is a numbers game, and there are far more juniors and mid-level engineers than seniors. A post that assumes production experience wins nods from a small audience; a post that explains the familiar case first and then improves on it gets comments from everyone. Two habits that do most of the work:

- Show the code the reader already writes, then the better version, in the same image. Nobody has to take the improvement on trust.
- Keep the advanced material for the first comment. Seniors who want depth will find it there and engage, and the post itself stays readable.

The tell that you have drifted the wrong way: the post explains *what the tool is* rather than *which problem it removes*. That reads as knowledge for its own sake, and it is the fastest way to lose the middle of your audience.

---

## 4. The first ninety minutes

This window decides how far the post travels.

1. Publish, then immediately post your own first comment (the extra detail, not a link).
2. Stay available for an hour. Reply to every comment with a question of your own — a reply that ends in a question doubles the chance of a thread, and threads count for more than isolated likes.
3. Reply properly: two to four sentences, one concrete detail, no "thanks!". A one-word reply spends the interaction without generating another.
4. Do not edit the post in the first hour. Fix typos afterwards, or in a comment.
5. Go and comment on five other posts while you wait. Your own activity in the window helps, and it feeds pillar 3.
6. Send the post to three or four people who genuinely care about the topic — as a DM with a sentence of context, never a mass tag. Tagging people who do not engage is a measurable negative signal.

---

## 5. Cadence and sequencing

Two to three posts a week, consistent slots, is the sweet spot: enough to stay in the feed, not enough to cannibalise your own reach. Leave at least 24 hours between posts, and never post two long ones back to back.

A four-week run from this folder:

| Week | Post | Format | Why here |
|---|---|---|---|
| 1 | `POST-A-four-tools-simple.md` | Text + 4 screenshots | Widest audience, lowest barrier to commenting; establishes the topic |
| 2 | `POST-C-short-opinion.md` | Text + 2 screenshots | Short and opinionated; harvests comments from week 1's new followers |
| 3 | `POST-B-rollback-story.md` | Text + 1 screenshot | Narrative, invites war stories, deepens authority |
| 4 | `CAROUSEL-SLIDES.md` | PDF document | Longest dwell time; also the artefact people save and share internally |

Best slots for engineering audiences: Tuesday–Thursday, 08:30–10:30 local to wherever most of your audience is. Check your own analytics after four posts and trust that over any general advice.

---

## 6. What reliably costs you reach

- Links in the body.
- Posting and leaving. No replies in the first hour is the single biggest self-inflicted wound.
- Reposting your own content without new commentary.
- Engagement bait — "comment YES for the PDF", polls with no purpose, follow-for-follow. It works once and damages the account's standing.
- Deleting and reposting a slow post within a day; the second attempt starts colder.
- Long unbroken paragraphs, ten hashtags, three CTAs.

---

## 7. Measuring properly

After 48 hours, look at the ratio, not the raw numbers:

- **Impressions** tell you whether the hook and the first audience worked.
- **Comments per 1 000 impressions** is the number worth optimising. Above ~5 is strong for technical content.
- **Saves and sends** indicate reference value — that is what code-screenshot posts should produce.
- **Profile views and follows** tell you whether the post attracted the right people, which is the only thing SSI pillars 2 and 4 respond to.

Keep a two-line log per post: hook used, format, comments per 1 000. After six posts the pattern in your own audience will be clearer than any general playbook, including this one.
