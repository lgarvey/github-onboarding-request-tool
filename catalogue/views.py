from django.http import Http404
from django.shortcuts import render

from catalogue.services import github_teams, terraform_config


def organisation_list(request):
    return render(
        request,
        "catalogue/organisation_list.html",
        {"organisations": terraform_config.list_organisations()},
    )


def organisation_detail(request, org):
    if org not in terraform_config.list_organisations():
        raise Http404("Unknown organisation")

    teams = terraform_config.get_teams(org)
    teams_by_slug = {team.slug: team for team in teams}
    slugs_by_id = {team_id: slug for slug, team_id in github_teams.get_team_ids(org).items()}
    team_rows = [
        {"team": team, "parent": teams_by_slug.get(slugs_by_id.get(team.parent_team_id))}
        for team in teams
    ]
    return render(
        request,
        "catalogue/organisation_detail.html",
        {
            "org": org,
            "repositories": terraform_config.get_repositories(org),
            "team_rows": team_rows,
        },
    )
