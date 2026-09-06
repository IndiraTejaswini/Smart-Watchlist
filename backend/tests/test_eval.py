from app.eval.replay_runner import FUNNEL, replay_runner, validate_funnel


def test_replay_artifact_is_fixed_and_conserved():
    artifact = replay_runner()
    assert artifact["symbols"] == 200
    assert artifact["sessions"] == 126
    assert validate_funnel()
    assert FUNNEL.evaluated - (
        FUNNEL.corporate_action + FUNNEL.market_wide + FUNNEL.sector_grouped + FUNNEL.below_cap
    ) == FUNNEL.surfaced


def test_replay_contract_contains_three_cases_and_two_continuation_groups():
    artifact = replay_runner()
    assert len(artifact["cases"]) == 3
    assert {row["category"] for row in artifact["continuation"]} == {
        "Explained by Filing",
        "Unexplained Abnormal Movement",
    }
