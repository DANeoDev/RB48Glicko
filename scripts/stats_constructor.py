def get_match_period(match):

    match_date = match[0][:10]

    year = int(match_date[:4])
    month = int(match_date[5:7])

    return year, month



def group_matches_by_month(matchhistory):

    monthly_matches = defaultdict(list)

    for match in matchhistory:

        period = get_match_period(match)

        monthly_matches[period].append(match)

    return monthly_matches