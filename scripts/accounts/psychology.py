"""Psychological evaluation, Jagged Alliance 2 (I.M.P.) style questionnaire, and persona archetype engine."""

PSYCHOLOGY_PERSONAS_EN = {
    "legend": {
        "key": "legend",
        "title": "The Locker Room Legend",
        "badge_icon": "🏆",
        "badge_tag": "Camaraderie & Banter",
        "passed": True,
        "tagline": "Football is life, but banter and cold drinks with teammates are eternal.",
        "description": (
            "You embody the true spirit of recreational football. You understand that Wednesday night sessions "
            "are about camaraderie, unforgettable crosses and tackles, and sharing banter over a cold drink afterwards. "
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
        "badge_tag": "Statistical Calculus",
        "passed": True,
        "tagline": "Variance is a familiar effect, sample sizes are adjustable, and ratings are descriptive models — not personal scores.",
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
        "tagline": "Unlucky deflections happen, offside calls are sometimes missed, and the ball just won't find the back of the net — the only thing that matters is tracking back.",
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

PSYCHOLOGY_PERSONAS_DE = {
    "legend": {
        "key": "legend",
        "title": "Die Kabinenlegende",
        "badge_icon": "🏆",
        "badge_tag": "Kameradschaft & Sprücheklopfer",
        "passed": True,
        "tagline": "Fußball ist unser Leben, aber die Sprüche und das Kaltgetränk danach sind für die Ewigkeit.",
        "description": (
            "Du verkörperst den wahren Geist des Freizeitfußballs. Du weißt, dass es beim Mittwochs-Kick um "
            "Kameradschaft, unvergessliche Flanken und Grätschen und das gemeinsame Labern bei einem kühlen Getränk danach geht. "
            "Für dich sind Glicko-Ratings eine interessante statistische Spielerei – sie werden niemals die "
            "pure Freude am Spiel überdecken."
        ),
        "traits": ["Immun gegen Rating-Toxizität", "Hohe Kabinenmoral", "Meister der Selbstironie", "Reine intrinsische Motivation"],
        "clearance_text": "FREIGABE ERTEILT. Du bist psychologisch bestens gerüstet, kompetitive Glicko-Ratings zu genießen, ohne die Teamharmonie zu gefährden.",
    },
    "tactician": {
        "key": "tactician",
        "title": "Der rationale Taktiker",
        "badge_icon": "📐",
        "badge_tag": "Statistisches Kalkül",
        "passed": True,
        "tagline": "Varianz ist ein bekannter Effekt, Stichprobengrößen anpassbar und Ratings sind beschreibende Modelle – keine Wertungen.",
        "description": (
            "Du schätzt die Eleganz mathematischer Modellierung. Du verstehst, dass Glicko-2 Siegwahrscheinlichkeiten "
            "auf Basis historischer Ergebnisse und Aufstellungen berechnet, kein Urteil über deinen menschlichen Wert. "
            "Du begreifst die Rating-Abweichung (RD) als statistische Unsicherheit und begegnest Schwankungen mit ruhiger Objektivität."
        ),
        "traits": ["Statistisches Verständnis", "Analytische Denkweise", "Objektives Fairplay", "Versteht Varianz"],
        "clearance_text": "FREIGABE ERTEILT. Deine analytische Gelassenheit und dein Verständnis der Rating-Mechanik machen dich zum idealen Glicko-Mitglied.",
    },
    "pragmatist": {
        "key": "pragmatist",
        "title": "Der Box-to-Box-Pragmatiker",
        "badge_icon": "🛡️",
        "badge_tag": "Widerstandsfähiger Kämpfer",
        "passed": True,
        "tagline": "Unglückliche Abpraller passieren, Abseits wird schon mal falsch angesagt und der Ball will vorne manchmal einfach nicht ins Eckige – das Einzige was zählt, ist nach hinten mitzuarbeiten.",
        "description": (
            "Besonnen, zäh und unbeeindruckt von turbulenten Spielverläufen. Wenn dein Team 0:3 in Rückstand gerät oder ein bitteres "
            "Eigentor kassiert, gerätst du nicht in Panik, machst keine Vorwürfe und grübelst nicht über Ratingpunkte – du krempelst "
            "die Ärmel hoch und konzentrierst dich auf den nächsten Zweikampf."
        ),
        "traits": ["Hohe emotionale Belastbarkeit", "Teamorientierte Haltung", "Unerschütterlicher Fokus", "Verlässlicher Mitspieler"],
        "clearance_text": "FREIGABE ERTEILT. Deine bodenständige Haltung garantiert, dass du mit dem Rating-System umgehen kannst, ohne den Fokus auf den Teamgeist zu verlieren.",
    },
    "tryhard": {
        "key": "tryhard",
        "title": "Der verbissene Stat-Stürmer",
        "badge_icon": "⚡",
        "badge_tag": "Rating-Obsessions-Risiko",
        "passed": False,
        "tagline": "Prüft die Rangliste auf dem Smartphone, noch bevor er dem Torwart die Hand gegeben hat.",
        "description": (
            "Bei dir besteht akute Gefahr, in die Falle kompetitiver Videospiele zu tappen: Du lässt zu, dass willkürliche "
            "Zahlen deine Laune und deinen Spaß am Freizeitsport bestimmen. Du neigst dazu, Spielergebnisse als persönliche "
            "Rating-Transaktionen zu verbuchen und überträgst Rating-Frust auf deine Mitspieler."
        ),
        "traits": ["Hohe Rating-Sensibilität", "Gefahr von Kabinenfrust", "Abhängigkeit von externer Bestätigung"],
        "clearance_text": "FREIGABE VERWEIGERT (Abkühlphase). Atme tief durch, erinnere dich daran, warum wir mit Freunden kicken, und wiederhole den Test, wenn du den Kopf frei hast.",
    },
    "conspiracy": {
        "key": "conspiracy",
        "title": "Der Aluhut-Theoretiker",
        "badge_icon": "🛸",
        "badge_tag": "Algorithmische Paranoia",
        "passed": False,
        "tagline": "Felsenfest überzeugt, dass der Webmaster die Glicko-Volatilitätskonstante persönlich manipuliert hat.",
        "description": (
            "Du glaubst, unerwartete Rating-Veränderungen seien kein Ergebnis statistischer Varianz oder Bayes'scher Updates, "
            "sondern eine geheime Verschwörung des Webmasters und der Datenbank-Admins, um deine Freizeitfußball-Karriere zu sabotieren."
        ),
        "traits": ["Misstrauen gegenüber Algorithmen", "Gibt der Platzpflege die Schuld", "Fordert manuelle Rating-Audits"],
        "clearance_text": "FREIGABE VERWEIGERT. Der Algorithmus hegt keine persönlichen Abneigungen. Wir empfehlen, das Tabellenblatt zu schließen, echten Rasen zu spüren und den Test später erneut zu machen.",
    },
    "fragile_ego": {
        "key": "fragile_ego",
        "title": "Der existenzielle Zweifler",
        "badge_icon": "🌧️",
        "badge_tag": "Rating-Angst",
        "passed": False,
        "tagline": "Ein Minus von 12 Ratingpunkten löst eine existenzielle Krise und Gedanken an das Karriereende aus.",
        "description": (
            "Du machst dein emotionales Wohlbefinden viel zu sehr von numerischen Kennzahlen abhängig. Ein Rating-Verlust nach einem "
            "hart umkämpften 4:5 fühlt sich wie ein persönlicher Schuldspruch an. Glicko-Ratings sind mathematische Schätzwerte "
            "vergangener Teamergebnisse, kein Urteil über deine menschliche Würde."
        ),
        "traits": ["Leistungsdruck", "Überidentifikation mit Zahlen", "Post-Match-Grübeln"],
        "clearance_text": "FREIGABE VERWEIGERT. Ratings existieren für den Spaß und ausgeglichene Teams, nicht zur Bestätigung deines Selbstwerts. Finde deine Leichtigkeit wieder und probiere es erneut!",
    },
}

# Default backwards-compatible aliases
PSYCHOLOGY_PERSONAS = PSYCHOLOGY_PERSONAS_EN

IMP_QUESTIONS_EN = [
    {
        "id": "q1",
        "scenario": "Scenario 1: Pre-Match Arrival",
        "question": "You arrive at the venue 15 minutes before kickoff. What is your primary pre-match routine?",
        "options": [
            ("a", "Practicing aggressive volleys towards players getting changed to intimidate the opponent right during warm-ups.", "tryhard"),
            ("b", "Methodical warm-up and stretching, analyzing attending players and possible team constellations.", "tactician"),
            ("c", "Checking your phone to see if the Webmaster has secretly adjusted your starting rating.", "conspiracy"),
            ("d", "First a quick smoke, trading weekend stories, and realizing you forgot to pack fresh underwear.", "legend"),
        ],
    },
    {
        "id": "q2",
        "scenario": "Scenario 2: The Selfish Teammate",
        "question": "Your teammate attempts a wild 35-meter volley with his weak foot when you were unmarked in front of an empty net. The ball lands on the roof of a parked car. Your reaction?",
        "options": [
            ("a", "Silently panic because that missed opportunity just cost your team 5 expected points.", "fragile_ego"),
            ("b", "Burst out laughing, applaud the audacity, and remind him he is buying the first round after the game.", "legend"),
            ("c", "Collapse onto the turf in agony, gesturing wildly about how this selfish play will destroy your rating.", "tryhard"),
            ("d", "Calmly point out that square passes generate an 88% higher conversion probability in small-sided football.", "tactician"),
        ],
    },
    {
        "id": "q3",
        "scenario": "Scenario 3: The 89th Minute Deflection",
        "question": "In the final minute of a tied match, a harmless cross takes a wild ricochet off a pebble, bounces off your shin, and trickles into your own net. You lose 4:5. How do you process this?",
        "options": [
            ("a", "Accept that stochastic variance is an inherent mathematical property of recreational sports.", "tactician"),
            ("b", "Demand an official investigation into pitch maintenance and the condition of the match ball.", "conspiracy"),
            ("c", "Shrug, high-five the opponent, and joke that you technically scored today.", "legend"),
            ("d", "Lock yourself in the shower stall for 20 minutes contemplating immediate retirement.", "fragile_ego"),
        ],
    },
    {
        "id": "q4",
        "scenario": "Scenario 4: The Underdog Prediction",
        "question": "The Matchmaker shows your team has an estimated win probability of only 34%. What thought immediately enters your head?",
        "options": [
            ("a", "The algorithm is clearly rigged by the administrators to artificially suppress my leaderboard ranking.", "conspiracy"),
            ("b", "Fantastic! That makes the underdog victory banter twice as sweet. Let's get out there!", "legend"),
            ("c", "An interesting Bayesian prior. Let's keep our shape compact and look for counter-pressing opportunities.", "tactician"),
            ("d", "Refuse to track back on defense because the algorithm has already decided the match is lost.", "tryhard"),
        ],
    },
    {
        "id": "q5",
        "scenario": "Scenario 5: Post-Match Pizza & Banter",
        "question": "After the session, a teammate pulls up the stats page on their phone over pizza. What is your perspective on the numbers?",
        "options": [
            ("a", "'Stats are fun, but did you see Bernhard's monster tackle? That's what really matters!'", "legend"),
            ("b", "'Looking at these numbers makes my stomach hurt. What if I drop two places next week?'", "fragile_ego"),
            ("c", "'It's a neat mathematical summary of historical results, not a personal verdict on anyone.'", "tactician"),
            ("d", "'My conservative rating is 1620 and yours is 1410, so I should take all corner kicks from now on.'", "tryhard"),
        ],
    },
    {
        "id": "q6",
        "scenario": "Scenario 6: The Day to Forget",
        "question": "You are having an off-day: your first touch bounces five meters away, you slip on every turn, and you give away an unnecessary penalty. What happens next?",
        "options": [
            ("a", "Recognize that individual performance follows a normal distribution and maintain tactical discipline.", "tactician"),
            ("b", "Fake a groin cramp at the 15-minute mark to sub off and protect your rating from dropping.", "tryhard"),
            ("c", "Kick a water bottle away in fury and claim the match ball was over-inflated on purpose.", "conspiracy"),
            ("d", "Laugh at yourself, work double-hard on defensive tracking, and let your teammates carry the attack.", "pragmatist"),
        ],
    },
    {
        "id": "q7",
        "scenario": "Scenario 7: The Glicko Clearance Philosophy",
        "question": "Why is access to the detailed Glicko rating tier gated behind this psychological evaluation?",
        "options": [
            ("a", "To keep people from immediately seeing how easily I could dominate the entire field.", "tryhard"),
            ("b", "Because competitive ratings can poison recreational enjoyment and intrinsic motivation if taken too seriously.", "legend"),
            ("c", "Because the Webmaster enjoys testing our loyalty with secret surveillance questions.", "conspiracy"),
            ("d", "To verify that players understand ratings model match results and variance, not human worth.", "tactician"),
        ],
    },
]

IMP_QUESTIONS_DE = [
    {
        "id": "q1",
        "scenario": "Szenario 1: Vor dem Anpfiff",
        "question": "Du triffst 15 Minuten vor Spielbeginn am Platz ein. Wie sieht deine typische Vorbereitung aus?",
        "options": [
            ("a", "Aggressive Volleyschüsse in Richtung der umziehenden Spieler üben, um den Gegner schon beim Aufwärmen einzuschüchtern.", "tryhard"),
            ("b", "Methodisches Aufwärmen und Dehnen, Analyse der anwesenden Spieler und möglicher Teamkonstellationen.", "tactician"),
            ("c", "Auf dem Handy checken, ob der Webmaster heimlich dein Start-Rating heruntergestuft hat.", "conspiracy"),
            ("d", "Erstmal ein Kippchen, Wochenendanekdoten austauschen und feststellen, dass man keine Wechselboxershorts eingepackt hat.", "legend"),
        ],
    },
    {
        "id": "q2",
        "scenario": "Szenario 2: Der eigensinnige Mitspieler",
        "question": "Dein Mitspieler versucht einen wilden 35-Meter-Volleyschuss mit dem schwachen Fuß, während du völlig blank vor dem leeren Tor stehst. Der Ball landet auf dem Dach eines Autos. Deine Reaktion?",
        "options": [
            ("a", "Innerlich in Panik geraten, weil diese vergebene Chance das Team gerade 5 erwartete Punkte gekostet hat.", "fragile_ego"),
            ("b", "In schallendes Gelächter ausbrechen, den Mut loben und ihn daran erinnern, dass er nach dem Spiel die erste Runde zahlt.", "legend"),
            ("c", "Verzweifelt auf den Rasen sinken und theatralisch gestikulieren, dass dieser Eigensinn dein Rating ruiniert.", "tryhard"),
            ("d", "Ruhig darauf hinweisen, dass Querpässe im Kleinfeldfußball eine um 88 % höhere Torwahrscheinlichkeit erzeugen.", "tactician"),
        ],
    },
    {
        "id": "q3",
        "scenario": "Szenario 3: Der abgefälschte Ball in der Schlussminute",
        "question": "Beim Stand von 4:4 in der letzten Spielminute prallt eine harmlose Flanke an einem Kieselstein ab, klatscht gegen dein Schienbein und kullert ins eigene Netz (Endstand 4:5). Wie verarbeitest du das?",
        "options": [
            ("a", "Akzeptieren, dass stochastische Varianz eine mathematische Grundeigenschaft des Freizeitsports ist.", "tactician"),
            ("b", "Eine offizielle Untersuchung der Platzbeschaffenheit und der Beschaffenheit des Spielballs einfordern.", "conspiracy"),
            ("c", "Mit den Schultern zucken, dem Gegner abklatschen und scherzen, dass du heute immerhin ein Tor erzielt hast.", "legend"),
            ("d", "Dich 20 Minuten lang in der Duschkabine einschließen und über das sofortige Karriereende nachdenken.", "fragile_ego"),
        ],
    },
    {
        "id": "q4",
        "scenario": "Szenario 4: Die Außenseiter-Prognose",
        "question": "Der Matchmaker zeigt an, dass dein Team eine vorhergesagte Siegchance von lediglich 34 % hat. Welcher Gedanke schießt dir durch den Kopf?",
        "options": [
            ("a", "Der Algorithmus ist vom Webmaster ganz klar manipuliert, um meine Platzierung künstlich zu drücken.", "conspiracy"),
            ("b", "Perfekt! Das macht den anschließenden Jubel über den Überraschungssieg doppelt süß. Rauf auf den Platz!", "legend"),
            ("c", "Ein interessanter Bayes'scher Prior. Lasst uns die Staffelung kompakter halten und auf Umschaltsituationen lauern.", "tactician"),
            ("d", "Die Rückwärtsbewegung verweigern, weil der Algorithmus das Spiel ja ohnehin schon als verloren gewertet hat.", "tryhard"),
        ],
    },
    {
        "id": "q5",
        "scenario": "Szenario 5: Pizza & Fachsimpeln nach dem Spiel",
        "question": "Nach dem Spiel holt ein Mitspieler beim Toni Häuschen die Statistikseite auf dem Smartphone heraus. Wie blickst du auf die Zahlen?",
        "options": [
            ("a", "'Zahlen machen Spaß, aber hast du Bernhards Monstergrätsche gesehen? Das ist es, worauf es ankommt!'", "legend"),
            ("b", "'Beim Anblick dieser Zahlen dreht sich mir der Magen um. Was, wenn ich nächste Woche zwei Plätze abrutsche?'", "fragile_ego"),
            ("c", "'Eine schöne mathematische Zusammenfassung vergangener Resultate, aber kein persönliches Urteil über jemanden.'", "tactician"),
            ("d", "'Mein konservatives Rating liegt bei 1620 und deines bei 1410 – ab sofort trete ich alle Ecken.'", "tryhard"),
        ],
    },
    {
        "id": "q6",
        "scenario": "Szenario 6: Der Tag zum Vergessen",
        "question": "Du hast einen rabenschwarzen Tag: Deine erste Ballannahme verspringt fünf Meter weit, du rutschst bei jedem Richtungswechsel weg und verursachst einen unnötigen Elfmeter. Was tust du?",
        "options": [
            ("a", "Erkennen, dass Einzelleistungen einer Normalverteilung unterliegen, und diszipliniert deine Position halten.", "tactician"),
            ("b", "Nach 15 Minuten einen Leistenkrampf vortäuschen, um dich auswechseln zu lassen und dein Rating zu retten.", "tryhard"),
            ("c", "Wütend eine Trinkflasche wegpfeffern und behaupten, dass der Spielball mit Absicht viel zu prall aufgepumpt war.", "conspiracy"),
            ("d", "Über dich selbst lachen, dafür in der Defensive doppelt so viele Meter fressen und die Kollegen wirbeln lassen.", "pragmatist"),
        ],
    },
    {
        "id": "q7",
        "scenario": "Szenario 7: Die Glicko-Philosophie",
        "question": "Warum ist der Zugriff auf das detaillierte Glicko-Rating an diesen psychologischen Fragebogen gekoppelt?",
        "options": [
            ("a", "Damit man nicht auf Anhieb sieht, wie mühelos ich das gesamte Teilnehmerfeld an die Wand spielen könnte.", "tryhard"),
            ("b", "Weil verbissene Ratings den Spaß am Freizeitsport und die intrinsische Spielfreude vergiften können, wenn man sie zu ernst nimmt.", "legend"),
            ("c", "Weil der Webmaster Freude daran hat, unsere Vereinstreue durch verdeckte Überwachungsfragen zu testen.", "conspiracy"),
            ("d", "Um sicherzustellen, dass die Spieler verstehen: Ratings modellieren Ergebnisse und Varianz, nicht den menschlichen Wert.", "tactician"),
        ],
    },
]

# Default backwards-compatible alias
IMP_QUESTIONS = IMP_QUESTIONS_EN


def get_psychology_personas(lang="de"):
    """Return localized persona archetypes dictionary."""
    return PSYCHOLOGY_PERSONAS_DE if lang == "de" else PSYCHOLOGY_PERSONAS_EN


def get_imp_questions(lang="de"):
    """Return localized list of I.M.P. questions."""
    return IMP_QUESTIONS_DE if lang == "de" else IMP_QUESTIONS_EN


def evaluate_psychology_submission(form_data, lang="de"):
    """Score the submitted questionnaire answers and assign a persona archetype."""
    scores = {
        "legend": 0,
        "tactician": 0,
        "pragmatist": 0,
        "tryhard": 0,
        "conspiracy": 0,
        "fragile_ego": 0,
    }

    questions = get_imp_questions(lang)
    for q in questions:
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
    
    personas = get_psychology_personas(lang)
    persona_info = personas.get(assigned_key, personas["legend"])

    return persona_info, scores
