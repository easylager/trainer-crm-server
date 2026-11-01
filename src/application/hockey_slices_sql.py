"""Общий SQL-фильтр матчей игры «Кто кого»: клубы (дома или в гостях) и лига источника (TASK-334).

Вынесен отдельно, чтобы ``hockey_game`` и ``hockey_slices`` не импортировали друг друга.
Параметры — ``Scope.params`` из ``hockey_slices``: ``clubs`` (список или NULL) и ``mleague``.
"""

SCOPE_SQL = """
      AND (CAST(:clubs AS text[]) IS NULL
           OR m.home_team = ANY(CAST(:clubs AS text[])) OR m.away_team = ANY(CAST(:clubs AS text[])))
      AND (CAST(:mleague AS text) IS NULL OR m.league = CAST(:mleague AS text))
"""
