"""Psychological evaluation, Jagged Alliance 2 (I.M.P.) style questionnaire, and persona archetype engine."""

PSYCHOLOGY_PERSONAS = {
    "legend": {
        "key": "legend",
        "title": "The Locker Room Legend",
        "badge_icon": "🏆",
        "badge_tag": "Camaraderie & Banter",
        "passed": True,
        "tagline": "Football is life, but banter and cold drinks with teammates are eternal.",
        "description": (
            "You embody the true spirit of recreational football. You understand that Tuesday night sessions "
            "are about camaraderie, unforgettable nutmegs, and sharing laughs over a cold drink afterwards. "
            "To you, Glicko ratings are just an interesting statistical curio — they will never overshadow "
            "the pure joy of the game."
        ),
        "traits": ["Immune to rating toxicity", "High Locker-Room Morale", "Master of Self-Irony", "Pure Intrinsic Motivation"],
        "clearance_text": "CLEARANCE GRANTED. You are psychologically fit to view and enjoy competitive Glicko ratings without endangering team harmony.",
    },
    "tactician": {
        "key": "tactician",
        "title": "The Rational Tactician",
        "badge_icon": "📐",
        "badge_tag": "Statistical Mastery",
        "passed": True,
        "tagline": "Variance is real, sample sizes matter, and ratings are descriptive models — not personal identity.",
        "description": (
            "You appreciate the elegance of mathematical modeling. You understand that Glicko-2 computes win probabilities "
            "based on historical results and lineup combinations, not an absolute measurement of intrinsic human worth. "
            "You recognize rating deviation (RD) as statistical uncertainty and view fluctuations with calm objectivity."
        ),
        "traits": ["Statistical Literacy", "Analytical Mindset", "Objective Sportsmanship", "Understands Variance"],
        "clearance_text": "CLEARANCE GRANTED. Your analytical detachment and grasp of rating mechanics make you an ideal Glicko tier member.",
    },
    "pragmatist": {
        "key": "pragmatist",
        "title": "The Box-to-Box Pragmatist",
        "badge_icon": "🛡️",
        "badge_tag": "Resilient Competitor",
        "passed": True,
        "tagline": "Bad bounces happen, referees miss calls, and the only thing that matters is tracking back.",
        "description": (
            "Level-headed, resilient, and unbothered by dramatic score swings. When your team goes down 0-3 or suffers a cruel "
            "own-goal deflection, you don't panic, blame others, or sulk about rating points — you roll up your sleeves and focus "
            "on the next play."
        ),
        "traits": ["High Emotional Resilience", "Team-First Attitude", "Unshakable Focus", "Reliable Teammate"],
        "clearance_text": "CLEARANCE GRANTED. Your practical attitude ensures you can engage with rating systems without losing focus on team sportsmanship.",
    },
    "tryhard": {
        "key": "tryhard",
        "title": "The Raging Stat-Striker",
        "badge_icon": "⚡",
        "badge_tag": "Rating Obsession Risk",
        "passed": False,
        "tagline": "Checking the leaderboard table before shaking hands with the goalkeeper.",
        "description": (
            "You are at high risk of falling into the competitive video game trap: allowing arbitrary numerical metrics "
            "to dictate your mood and enjoyment of recreational sports. You tend to treat match outcomes as personal rating "
            "transactions and risk projecting rating anxiety onto teammates."
        ),
        "traits": ["High Rating Sensitivity", "Locker Room Friction Risk", "External Gratification Dependency"],
        "clearance_text": "CLEARANCE DENIED (Cooling-Off Period). Please take a deep breath, reflect on why we play recreational football with friends, and retake the assessment when ready.",
    },
    "conspiracy": {
        "key": "conspiracy",
        "title": "The Tin-Foil Theorist",
        "badge_icon": "🛸",
        "badge_tag": "Algorithmic Paranoia",
        "passed": False,
        "tagline": "Convinced the Glicko volatility constant is personally rigged by the Webmaster.",
        "description": (
            "You believe unexpected rating fluctuations are not the result of statistical variance or Bayesian updates, "
            "but rather a secret conspiracy orchestrated by the Webmaster and database administrators to stunt your "
            "recreational football career."
        ),
        "traits": ["Algorithmic Suspicion", "Blames Turf Maintenance", "Demands Manual Rating Audits"],
        "clearance_text": "CLEARANCE DENIED. The algorithm has no personal grudges. We recommend stepping away from the spreadsheet, touching some real pitch grass, and retaking the assessment.",
    },
    "fragile_ego": {
        "key": "fragile_ego",
        "title": "The Existential Doubter",
        "badge_icon": "🌧️",
        "badge_tag": "Rating Anxiety",
        "passed": False,
        "tagline": "A 12-point rating dip induces an existential crisis and contemplation of retirement.",
        "description": (
            "You tie too much of your emotional equilibrium to numerical indicators. A rating drop after a tough 4:5 match "
            "feels like a personal indictment. Glicko ratings are mathematical estimates of past team results, not an evaluation "
            "of your human dignity or worth as a person."
        ),
        "traits": ["Performance Anxiety", "Over-Identification with Numbers", "Post-Match Rumination"],
        "clearance_text": "CLEARANCE DENIED. Ratings exist for fun and match balancing, not self-worth validation. Re-calibrate your perspective on recreational banter and try again!",
    },
}

IMP_QUESTIONS = [
    {
        "id": "q1",
        "scenario": "Scenario 1: Pre-Match Arrival",
        "question": "You arrive at the venue 15 minutes before kickoff. What is your primary pre-match routine?",
        "options": [
            ("a", "Stretch methodically, calculate pitch friction, and analyze historical team balance.", "tactician"),
            ("b", "Crack a joke with the keeper, open a cold drink, and check if anyone forgot shinpads.", "legend"),
            ("c", "Aggressively practice bicycle kicks against the locker room lockers to intimidate the other side.", "tryhard"),
            ("d", "Check your phone to see if the Webmaster has secretly adjusted your starting rating.", "conspiracy"),
        ],
    },
    {
        "id": "q2",
        "scenario": "Scenario 2: The Selfish Teammate",
        "question": "Your teammate attempts a wild 35-meter volley with his weak foot when you were unmarked in front of an empty net. The ball lands on the roof of a parked car. Your reaction?",
        "options": [
            ("a", "Burst out laughing, applaud the audacity, and remind him he is buying the first round after the game.", "legend"),
            ("b", "Calmly mention that square passes have an 88% higher conversion probability in small-sided football.", "tactician"),
            ("c", "Collapse onto the turf in agony, gesturing wildly about how this selfish play will destroy your rating.", "tryhard"),
            ("d", "Silently panic because that missed opportunity just cost your team 5 expected points.", "fragile_ego"),
        ],
    },
    {
        "id": "q3",
        "scenario": "Scenario 3: The 89th Minute Deflection",
        "question": "In the final minute of a tied match, a harmless cross takes a wild ricochet off a pebble, bounces off your shin, and trickles into your own net. You lose 4:5. How do you process this?",
        "options": [
            ("a", "Shrug, high-five the opponent, and joke that you technically scored today.", "legend"),
            ("b", "Accept that stochastic variance is an inherent mathematical property of recreational sports.", "tactician"),
            ("c", "Demand an official investigation into the pitch owner's turf maintenance and the referee's eyesight.", "conspiracy"),
            ("d", "Lock yourself in the shower stall for 20 minutes contemplating immediate retirement.", "fragile_ego"),
        ],
    },
    {
        "id": "q4",
        "scenario": "Scenario 4: The Underdog Prediction",
        "question": "The Matchmaker shows your team has an estimated win probability of only 34%. What thought immediately enters your head?",
        "options": [
            ("a", "Fantastic! That makes the underdog victory banter twice as sweet. Let's get out there!", "legend"),
            ("b", "An interesting Bayesian prior. Let's adjust our defensive shape and look for counter-pressing opportunities.", "tactician"),
            ("c", "Refuse to track back on defense because the algorithm has already decided the match is lost.", "tryhard"),
            ("d", "The algorithm is clearly rigged by the administrators to artificially suppress my leaderboard ranking.", "conspiracy"),
        ],
    },
    {
        "id": "q5",
        "scenario": "Scenario 5: Post-Match Pizza & Banter",
        "question": "After the session, a teammate pulls up the stats page on their phone over pizza. What is your perspective on the numbers?",
        "options": [
            ("a", "'Stats are fun, but did you see Max's backheel nutmeg? That's what really matters.'", "legend"),
            ("b", "'It's a neat mathematical summary of historical results, not a personal verdict on anyone.'", "tactician"),
            ("c", "'My conservative rating is 1620 and yours is 1410, so I should take all corner kicks from now on.'", "tryhard"),
            ("d", "'Looking at these numbers makes my stomach hurt. What if I drop two places next week?'", "fragile_ego"),
        ],
    },
    {
        "id": "q6",
        "scenario": "Scenario 6: The Total Nightmare Performance",
        "question": "You are having an off-day: your first touch bounces five meters away, you slip on every turn, and you miss a penalty. What happens next?",
        "options": [
            ("a", "Laugh at yourself, work double-hard on defensive tracking, and let your teammates carry the attack.", "pragmatist"),
            ("b", "Recognize that individual performance follows a normal distribution and maintain tactical discipline.", "tactician"),
            ("c", "Fake a groin cramp at the 15-minute mark to sub off and protect your rating from dropping.", "tryhard"),
            ("d", "Kick a water bottle into the stands and complain that the ball was over-inflated on purpose.", "conspiracy"),
        ],
    },
    {
        "id": "q7",
        "scenario": "Scenario 7: The Glicko Clearance Philosophy",
        "question": "Why is access to the detailed Glicko rating tier gated behind this psychological evaluation?",
        "options": [
            ("a", "Because competitive ratings can poison recreational enjoyment and intrinsic motivation if taken too seriously.", "legend"),
            ("b", "To verify that players understand ratings model match results and variance, not human worth.", "tactician"),
            ("c", "To keep me from seeing how easily I could dominate the entire leaderboard.", "tryhard"),
            ("d", "Because the Webmaster enjoys testing our loyalty with secret surveillance questions.", "conspiracy"),
        ],
    },
]


def evaluate_psychology_submission(form_data):
    """Score the submitted questionnaire answers and assign a persona archetype."""
    scores = {
        "legend": 0,
        "tactician": 0,
        "pragmatist": 0,
        "tryhard": 0,
        "conspiracy": 0,
        "fragile_ego": 0,
    }

    for q in IMP_QUESTIONS:
        selected_val = form_data.get(q["id"])
        matching_opt = next((opt for opt in q["options"] if opt[0] == selected_val), None)
        if matching_opt:
            scores[matching_opt[2]] += 1
        else:
            # Default fall-back
            scores["legend"] += 1

    # Find dominant persona
    # Tie-breaking priority: legend -> tactician -> pragmatist -> tryhard -> conspiracy -> fragile_ego
    priority = ["legend", "tactician", "pragmatist", "tryhard", "conspiracy", "fragile_ego"]
    sorted_personas = sorted(priority, key=lambda k: scores[k], reverse=True)
    assigned_key = sorted_personas[0]
    persona_info = PSYCHOLOGY_PERSONAS.get(assigned_key, PSYCHOLOGY_PERSONAS["legend"])

    return persona_info, scores
