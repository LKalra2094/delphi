"""One-off generator for the committed seed JSON. Deterministic (fixed seed).

Produces ~200 rows per table, spread across all 6 domains, mixed sentiment
(~40% negative / 25% neutral / 35% positive), dates across the last ~90 days.
Run once; the JSON it writes is the source of truth committed to the repo.
"""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
RNG = random.Random(42)
NOW = datetime(2026, 7, 2, tzinfo=timezone.utc)

DOMAINS = ["search", "checkout", "delivery", "returns", "payments", "account"]

# (body, title) fragments per domain per sentiment.
POS = {
    "search": [
        ("Search finally understands typos — found what I wanted instantly.", "Search got smart"),
        ("Autocomplete suggestions are spot on now, love it.", "Great autocomplete"),
        ("Filters make narrowing down products so easy.", "Filters are great"),
        ("Found an obscure item on the first try. Relevance is excellent.", "Relevance nailed it"),
    ],
    "checkout": [
        ("Checkout was three taps and done. Promo code applied perfectly.", "Fast checkout"),
        ("Guest checkout is smooth and quick.", "Smooth guest checkout"),
        ("Cart saved my items across devices. Very convenient.", "Cart syncs well"),
        ("No surprise fees at checkout, exactly what I expected.", "Transparent pricing"),
    ],
    "delivery": [
        ("Curbside pickup was fast and the app tracking was accurate.", "Love the pickup flow"),
        ("Same-day delivery arrived early. Impressed.", "Early delivery"),
        ("Tracking updates were precise the whole way.", "Accurate tracking"),
        ("Driver handoff was seamless and friendly.", "Great handoff"),
    ],
    "returns": [
        ("Refund hit my card in two days. Painless return.", "Fast refund"),
        ("Return label printed instantly, super easy.", "Easy returns"),
        ("Exchange flow was clear and quick.", "Smooth exchange"),
        ("Drop-off return took two minutes. Great experience.", "Quick drop-off"),
    ],
    "payments": [
        ("Saved cards and wallet checkout work flawlessly.", "Wallet works great"),
        ("Gift card applied with no issues at all.", "Gift card worked"),
        ("Refund to my card was quick and clearly itemized.", "Clean refund"),
        ("Apple Pay made paying effortless.", "Effortless payment"),
    ],
    "account": [
        ("Login with MFA is smooth now, thanks.", "MFA is smooth"),
        ("Password reset took seconds. No friction.", "Easy reset"),
        ("Managing addresses in my profile is simple.", "Simple profile"),
        ("Loyalty rewards are clearly shown and easy to redeem.", "Great loyalty UX"),
    ],
}
NEU = {
    "search": [
        ("Search is okay but ranking could be better for brand names.", "Search is fine"),
        ("Autocomplete works, though it misses some categories.", "Decent autocomplete"),
    ],
    "checkout": [
        ("Checkout is fine but the address form is a bit long.", "Checkout is okay"),
        ("Promo field is easy to miss but works once found.", "Promo field hidden"),
    ],
    "delivery": [
        ("Delivery window was accurate but wide. Acceptable.", "Wide window"),
        ("Tracking updated eventually, a little slow.", "Slow tracking updates"),
    ],
    "returns": [
        ("Return worked but the policy page was confusing.", "Confusing policy"),
        ("Refund arrived, took about a week. Average.", "Average refund time"),
    ],
    "payments": [
        ("Payment went through but the receipt email was delayed.", "Delayed receipt"),
        ("Card entry is fine, wish it saved automatically.", "No auto-save"),
    ],
    "account": [
        ("Account settings are fine, layout is a bit dated.", "Dated settings UI"),
        ("Login works but session logs me out often.", "Frequent logout"),
    ],
}
NEG = {
    "search": [
        ("I searched for 'AA batteries' and got zero results. Search is broken.", "Search never finds anything"),
        ("Every misspelling returns nothing. Useless search.", "Typos break search"),
        ("Relevant products buried under sponsored junk.", "Bad ranking"),
        ("Filters reset every time I go back. Infuriating.", "Filters keep resetting"),
    ],
    "checkout": [
        ("Payment page spins forever and my promo code won't apply.", "Checkout keeps failing"),
        ("App crashed twice during checkout and lost my cart.", "Checkout crashes"),
        ("Surprise fees appeared only at the final step.", "Hidden fees at checkout"),
        ("Guest checkout forced me to make an account. Abandoned.", "Forced account creation"),
    ],
    "delivery": [
        ("Package marked delivered but never arrived.", "Missing delivery"),
        ("Delivery was three days late with no updates.", "Late delivery"),
        ("Item arrived damaged and tracking was wrong the whole time.", "Damaged and mistracked"),
        ("Curbside pickup made me wait 40 minutes.", "Pickup wait too long"),
    ],
    "returns": [
        ("Return took three weeks to refund. Frustrating.", "Refund took forever"),
        ("Couldn't generate a return label, support was no help.", "Return label broken"),
        ("Charged a restocking fee that wasn't disclosed.", "Hidden restocking fee"),
        ("Exchange never processed, had to call twice.", "Exchange failed"),
    ],
    "payments": [
        ("Card was double-charged on one order.", "Double charged"),
        ("My saved card keeps getting declined for no reason.", "Card declined"),
        ("Refund to card still missing after two weeks.", "Refund missing"),
        ("Authorization hold locked up funds for days.", "Auth hold too long"),
    ],
    "account": [
        ("Locked out of my account and MFA codes never arrive.", "Account lockout"),
        ("Password reset email never comes through.", "Reset email broken"),
        ("Got logged out mid-order and lost everything.", "Session expired mid-order"),
        ("Can't update my address, form throws an error.", "Address update fails"),
    ],
}

AUTHORS = ["jenny_r", "marcus88", "dana_k", "sam_lee", "priya_n", "tom_h", "aisha_b",
           "leo_m", "kim_w", "raj_p", "nina_c", "omar_s", "beth_l", "carlos_d", "mei_x"]
APP_SOURCES = ["app_store", "play_store"]
SURVEY_CHANNELS = ["survey", "support_ticket", "nps"]


def pick_sentiment() -> str:
    r = RNG.random()
    if r < 0.40:
        return "negative"
    if r < 0.65:
        return "neutral"
    return "positive"


def rand_dt() -> str:
    days = RNG.randint(0, 89)
    secs = RNG.randint(0, 86399)
    dt = NOW - timedelta(days=days, seconds=secs)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def frag(bank: dict, domain: str, sentiment: str):
    key = {"positive": POS, "neutral": NEU, "negative": NEG}[sentiment]
    return RNG.choice(key[domain])


def rating_for(sentiment: str) -> float:
    return {"positive": RNG.choice([4.0, 5.0]),
            "neutral": 3.0,
            "negative": RNG.choice([1.0, 2.0])}[sentiment]


def nps_for(sentiment: str) -> int:
    return {"positive": RNG.randint(9, 10),
            "neutral": RNG.randint(7, 8),
            "negative": RNG.randint(0, 6)}[sentiment]


def gen_reviews_store(n: int) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        domain = DOMAINS[i % len(DOMAINS)]
        sentiment = pick_sentiment()
        body, title = frag(POS, domain, sentiment)
        rows.append({
            "ext_id": f"as_{i:04d}",
            "source": RNG.choice(APP_SOURCES),
            "title": title,
            "body": body,
            "rating": rating_for(sentiment),
            "author": RNG.choice(AUTHORS),
            "sentiment": sentiment,
            "review_dt": rand_dt(),
            "domain_tag": domain,
        })
    return rows


def gen_feedback_survey(n: int) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        domain = DOMAINS[(i + 3) % len(DOMAINS)]
        sentiment = pick_sentiment()
        body, _ = frag(POS, domain, sentiment)
        channel = RNG.choice(SURVEY_CHANNELS)
        rows.append({
            "ext_id": f"sv_{i:04d}",
            "channel": channel,
            "body": body,
            "nps_score": nps_for(sentiment),
            "order_id": (f"ORD-{RNG.randint(90000, 99999)}"
                         if RNG.random() > 0.2 else None),
            "sentiment": sentiment,
            "feedback_dt": rand_dt(),
            "domain_tag": domain,
        })
    return rows


if __name__ == "__main__":
    store = gen_reviews_store(210)
    survey = gen_feedback_survey(205)
    (HERE / "seed_reviews_store.json").write_text(json.dumps(store, indent=2))
    (HERE / "seed_feedback_survey.json").write_text(json.dumps(survey, indent=2))
    print(f"Wrote {len(store)} reviews_store and {len(survey)} feedback_survey rows.")
