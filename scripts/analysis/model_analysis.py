import math
from flask import has_request_context, request
from scripts.glicko.glicko2 import BOX, DEFAULT_SIGMA, GLICKO2_SCALE, HF, IGNORED_RD, TOTAL
from scripts.database.db_matches import get_match_teams, get_matches
from scripts.database.db_ratings import get_match_ratings


def _expected_score(team_a, team_b):
    mu_a = (team_a['rating'] - 1500.0) / GLICKO2_SCALE
    mu_b = (team_b['rating'] - 1500.0) / GLICKO2_SCALE
    phi_b = team_b['rd'] / GLICKO2_SCALE
    impact = 1 / math.sqrt(1 + (3 * phi_b**2) / (math.pi**2))
    return 1 / (1 + math.exp(-impact * (mu_a - mu_b)))


def _team_rating(player_ids, total_players, ratings, rating_type):
    if not player_ids:
        return None
    ignored_players = total_players - len(player_ids)
    average_rating = sum(ratings[p][rating_type]['rating'] for p in player_ids) / len(player_ids)
    average_rd = math.sqrt((sum(ratings[p][rating_type]['rd'] ** 2 for p in player_ids) + IGNORED_RD**2 * ignored_players) / total_players)
    average_sigma = math.sqrt((sum(ratings[p][rating_type]['sigma'] ** 2 for p in player_ids) + DEFAULT_SIGMA**2 * ignored_players) / total_players)
    return {'rating': average_rating, 'rd': average_rd, 'sigma': average_sigma}


def _actual_score(match):
    if match['goals_a'] > match['goals_b']:
        return 1.0
    if match['goals_a'] < match['goals_b']:
        return 0.0
    return 0.5


def _favourite_observation(prediction, actual):
    return (prediction, actual) if prediction > 0.5 else (1.0 - prediction, 1.0 - actual)


def _log_loss(prediction, actual):
    prediction = min(max(prediction, 1e-15), 1 - 1e-15)
    return -(actual * math.log(prediction) + (1 - actual) * math.log(1 - prediction))


def _goal_diff_percentiles(observations):
    by_pitch = {}
    for item in observations:
        by_pitch.setdefault(item['pitch'], []).append(item['goal_diff'])
    percentile_by_pitch, reference = {}, {}
    for pitch, values in by_pitch.items():
        values = sorted(values); count = len(values); percentile_by_pitch[pitch] = {}; reference[pitch] = []
        for value in sorted(set(values)):
            percentile = (sum(other < value for other in values) + 0.5 * sum(other == value for other in values)) / count
            percentile_by_pitch[pitch][value] = percentile
            reference[pitch].append({'goal_diff': value, 'percentile': percentile, 'count': values.count(value)})
    for item in observations:
        item['goal_diff_percentile'] = percentile_by_pitch[item['pitch']][item['goal_diff']]
    return reference


def _quantile_baskets(predictions):
    count = len(predictions); basket_count = 20 if count >= 200 else 10
    ordered = sorted(predictions, key=lambda item: item['prediction']); baskets = []
    for index in range(basket_count):
        values = ordered[index * count // basket_count:(index + 1) * count // basket_count]
        if not values:
            continue
        p = [x['prediction'] for x in values]; a = [x['actual'] for x in values]; g = [x['goal_diff_percentile'] for x in values]
        baskets.append({'label': f"{min(p)*100:.1f}–{max(p)*100:.1f}%", 'count': len(values), 'predicted': sum(p)/len(p), 'actual': sum(a)/len(a), 'goal_diff_percentile': sum(g)/len(g)})
    return baskets


def _brier_baskets(observations):
    count = len(observations); basket_count = 20 if count >= 200 else 10
    ordered = sorted(observations, key=lambda item: item['prediction']); baskets = []
    for index in range(basket_count):
        values = ordered[index * count // basket_count:(index + 1) * count // basket_count]
        if values:
            baskets.append({'count': len(values), 'predicted': sum(x['prediction'] for x in values)/len(values), 'actual': sum(x['actual'] for x in values)/len(values)})
    return baskets


def _lowess(predictions, value_key='actual', points=50, fraction=0.35):
    if len(predictions) < 10:
        return []
    ordered = sorted(predictions, key=lambda item: item['prediction']); xs = [x['prediction'] for x in ordered]; ys = [x[value_key] for x in ordered]; n = len(xs); span = max(3, int(math.ceil(fraction*n))); curve = []
    for step in range(points):
        x0 = step / (points - 1); distances = [abs(x-x0) for x in xs]; bandwidth = sorted(distances)[min(span-1,n-1)]
        weights = [1.0 if d == 0 else 0.0 for d in distances] if bandwidth == 0 else [(1-(d/bandwidth)**3)**3 if d <= bandwidth else 0.0 for d in distances]
        weight_sum = sum(weights)
        if not weight_sum:
            continue
        mean_x = sum(w*x for w,x in zip(weights,xs))/weight_sum; mean_y = sum(w*y for w,y in zip(weights,ys))/weight_sum
        sxx = sum(w*(x-mean_x)**2 for w,x in zip(weights,xs)); sxy = sum(w*(x-mean_x)*(y-mean_y) for w,x,y in zip(weights,xs,ys)); slope = sxy/sxx if sxx > 1e-12 else 0.0
        curve.append({'predicted': x0, value_key: min(1.0,max(0.0,mean_y+slope*(x0-mean_x)))} )
    return curve


def _brier_decomposition(observations):
    decisive = [x for x in observations if x['actual'] in (0.0, 1.0)]
    if not decisive:
        return {'games': 0, 'brier': None, 'baseline_50': None, 'baseline_base_rate': None, 'base_rate': None, 'brier_skill_50': None, 'brier_skill_base_rate': None, 'reliability': None, 'resolution': None, 'uncertainty': None}
    n = len(decisive); base_rate = sum(x['actual'] for x in decisive)/n
    brier = sum((x['prediction']-x['actual'])**2 for x in decisive)/n; baseline_50 = 0.25; baseline_base_rate = sum((base_rate-x['actual'])**2 for x in decisive)/n
    reliability = resolution = 0.0
    for basket in _brier_baskets(decisive):
        weight = basket['count']/n; reliability += weight*(basket['predicted']-basket['actual'])**2; resolution += weight*(basket['actual']-base_rate)**2
    uncertainty = base_rate*(1-base_rate)
    return {'games': n, 'brier': brier, 'baseline_50': baseline_50, 'baseline_base_rate': baseline_base_rate, 'base_rate': base_rate, 'brier_skill_50': 1-brier/baseline_50, 'brier_skill_base_rate': 1-brier/baseline_base_rate if baseline_base_rate > 0 else None, 'reliability': reliability, 'resolution': resolution, 'uncertainty': uncertainty}


def analyze_model(connection, mode=TOTAL, pitch=None):
    if mode not in (TOTAL, 'pitch'):
        raise ValueError("mode must be 'total' or 'pitch'")
    if pitch is None and mode == 'pitch' and has_request_context():
        pitch = request.args.get('pitch', BOX)
    if pitch not in (None, BOX, HF):
        raise ValueError("pitch must be None, BOX, or HF")
    observations=[]; excluded=0
    for match in get_matches(connection).values():
        if pitch is not None and match['pitch'] != pitch: continue
        rating_type = TOTAL
        if mode == 'pitch':
            rating_type = BOX if match['pitch'] == BOX else HF if match['pitch'] == HF else None
            if rating_type is None: excluded += 1; continue
        team_a_ids, team_b_ids = get_match_teams(connection, match['match_id'])
        if not team_a_ids or not team_b_ids: excluded += 1; continue
        ratings = get_match_ratings(connection, match['match_id'])
        if any(p not in ratings or rating_type not in ratings[p] for p in team_a_ids + team_b_ids): excluded += 1; continue
        team_a = _team_rating(team_a_ids, match['players_a'], ratings, rating_type); team_b = _team_rating(team_b_ids, match['players_b'], ratings, rating_type)
        if team_a is None or team_b is None: excluded += 1; continue
        raw = _expected_score(team_a, team_b)
        if math.isclose(raw, 0.5, abs_tol=1e-12): excluded += 1; continue
        prediction, actual = _favourite_observation(raw, _actual_score(match))
        observations.append({'prediction': prediction, 'actual': actual, 'pitch': match['pitch'], 'goal_diff': abs(match['goals_a']-match['goals_b'])})
    if not observations:
        return {'mode':mode,'pitch':pitch,'games':0,'excluded':excluded,'brier':None,'log_loss':None,'mean_absolute_error':None,'accuracy':None,'calibration':[],'lowess':[],'goal_diff_lowess':[],'goal_diff_reference':{},'brier_decomposition':_brier_decomposition([])}
    reference = _goal_diff_percentiles(observations); count=len(observations); brier=sum((x['prediction']-x['actual'])**2 for x in observations)/count; log_loss=sum(_log_loss(x['prediction'],x['actual']) for x in observations)/count; mae=sum(abs(x['prediction']-x['actual']) for x in observations)/count; decisive=[x for x in observations if x['actual'] in (0.0,1.0)]; accuracy=sum(x['actual']==1.0 for x in decisive)/len(decisive) if decisive else None
    return {'mode':mode,'pitch':pitch,'games':count,'excluded':excluded,'brier':brier,'log_loss':log_loss,'mean_absolute_error':mae,'accuracy':accuracy,'calibration':_quantile_baskets(observations),'lowess':_lowess(observations,'actual'),'goal_diff_lowess':_lowess(observations,'goal_diff_percentile'),'goal_diff_reference':reference,'brier_decomposition':_brier_decomposition(observations)}
