from __future__ import annotations

import uuid
from typing import Any, Dict


def _graphql(
    client,
    query: str,
    variables: Dict[str, Any] | None = None,
    token: str | None = None,
):
    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )


def _register_and_login_graphql(client, prefix: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    register_mutation = """
    mutation Register($name: String!, $email: String!, $password: String!) {
      registerUser(name: $name, email: $email, password: $password) {
        message
      }
    }
    """
    email = f"{prefix}-{suffix}@email.com"
    register_response = _graphql(
        client,
        register_mutation,
        {
            "name": f"{prefix}-{suffix}",
            "email": email,
            "password": "StrongPass@123",
        },
    )
    assert register_response.status_code == 200
    assert "errors" not in register_response.get_json()

    login_mutation = """
    mutation Login($email: String!, $password: String!) {
      login(email: $email, password: $password) {
        token
      }
    }
    """
    login_response = _graphql(
        client,
        login_mutation,
        {"email": email, "password": "StrongPass@123"},
    )
    assert login_response.status_code == 200
    login_body = login_response.get_json()
    assert "errors" not in login_body
    token = login_body["data"]["login"]["token"]
    assert token
    return token


def test_graphql_goals_crud_flow(client) -> None:
    token = _register_and_login_graphql(client, "goal-graphql")

    create_mutation = """
    mutation CreateGoal($title: String!, $targetAmount: String!) {
      createGoal(title: $title, targetAmount: $targetAmount, priority: 2) {
        message
        goal { id title targetAmount currentAmount priority status }
      }
    }
    """
    create_response = _graphql(
        client,
        create_mutation,
        {"title": "Comprar carro", "targetAmount": "40000.00"},
        token=token,
    )
    assert create_response.status_code == 200
    create_body = create_response.get_json()
    assert "errors" not in create_body
    goal_id = create_body["data"]["createGoal"]["goal"]["id"]
    assert create_body["data"]["createGoal"]["goal"]["status"] == "active"

    list_query = """
    query ListGoals {
      goals(page: 1, perPage: 10, status: "active") {
        items { id title status targetAmount }
        pagination { total page perPage }
      }
    }
    """
    list_response = _graphql(client, list_query, token=token)
    assert list_response.status_code == 200
    list_body = list_response.get_json()
    assert "errors" not in list_body
    assert list_body["data"]["goals"]["pagination"]["total"] >= 1
    assert any(item["id"] == goal_id for item in list_body["data"]["goals"]["items"])

    get_query = """
    query GetGoal($goalId: UUID!) {
      goal(goalId: $goalId) {
        id
        title
        targetAmount
      }
    }
    """
    get_response = _graphql(client, get_query, {"goalId": goal_id}, token=token)
    assert get_response.status_code == 200
    get_body = get_response.get_json()
    assert "errors" not in get_body
    assert get_body["data"]["goal"]["id"] == goal_id

    update_mutation = """
    mutation UpdateGoal($goalId: UUID!) {
      updateGoal(goalId: $goalId, currentAmount: "10000.00", status: PAUSED) {
        message
        goal { id currentAmount status }
      }
    }
    """
    update_response = _graphql(
        client, update_mutation, {"goalId": goal_id}, token=token
    )
    assert update_response.status_code == 200
    update_body = update_response.get_json()
    assert "errors" not in update_body
    assert update_body["data"]["updateGoal"]["goal"]["status"] == "paused"
    assert update_body["data"]["updateGoal"]["goal"]["currentAmount"] == "10000.00"

    profile_mutation = """
    mutation UpdateProfile {
      updateUserProfile(
        monthlyIncome: 10000
        monthlyExpenses: 5500
        monthlyInvestment: 1400
      ) {
        user { id }
      }
    }
    """
    profile_response = _graphql(client, profile_mutation, token=token)
    assert profile_response.status_code == 200
    assert "errors" not in profile_response.get_json()

    goal_plan_query = """
    query GoalPlan($goalId: UUID!) {
      goalPlan(goalId: $goalId) {
        horizon
        goalHealth
        remainingAmount
        projectedMonthlyContribution
        recommendedMonthlyContribution
        estimatedCompletionDate
        recommendations { priority title action estimatedDate }
      }
    }
    """
    plan_response = _graphql(client, goal_plan_query, {"goalId": goal_id}, token=token)
    assert plan_response.status_code == 200
    plan_body = plan_response.get_json()
    assert "errors" not in plan_body
    assert plan_body["data"]["goalPlan"]["goalHealth"] in {
        "on_track",
        "at_risk",
        "off_track",
        "completed",
    }
    assert isinstance(plan_body["data"]["goalPlan"]["recommendations"], list)

    simulate_mutation = """
    mutation SimulateGoalPlan {
      simulateGoalPlan(
        targetAmount: "50000.00"
        currentAmount: "15000.00"
        monthlyIncome: "12000.00"
        monthlyExpenses: "7000.00"
        monthlyContribution: "2500.00"
        targetDate: "2029-12-31"
      ) {
        message
        goalPlan {
          horizon
          goalHealth
          estimatedCompletionDate
          recommendations { priority title }
        }
      }
    }
    """
    simulation_response = _graphql(client, simulate_mutation, token=token)
    assert simulation_response.status_code == 200
    simulation_body = simulation_response.get_json()
    assert "errors" not in simulation_body
    assert (
        simulation_body["data"]["simulateGoalPlan"]["message"]
        == "Simulação da meta calculada com sucesso"
    )
    assert simulation_body["data"]["simulateGoalPlan"]["goalPlan"]["goalHealth"] in {
        "on_track",
        "at_risk",
        "off_track",
        "completed",
    }

    delete_mutation = """
    mutation DeleteGoal($goalId: UUID!) {
      deleteGoal(goalId: $goalId) {
        ok
        message
      }
    }
    """
    delete_response = _graphql(
        client, delete_mutation, {"goalId": goal_id}, token=token
    )
    assert delete_response.status_code == 200
    delete_body = delete_response.get_json()
    assert "errors" not in delete_body
    assert delete_body["data"]["deleteGoal"]["ok"] is True

    missing_response = _graphql(client, get_query, {"goalId": goal_id}, token=token)
    missing_body = missing_response.get_json()
    assert missing_response.status_code == 200
    assert missing_body["data"]["goal"] is None
    assert missing_body["errors"][0]["extensions"]["code"] == "NOT_FOUND"


def test_graphql_goals_forbidden_for_non_owner(client) -> None:
    owner_token = _register_and_login_graphql(client, "goal-owner")
    other_token = _register_and_login_graphql(client, "goal-other")

    create_mutation = """
    mutation CreateGoal {
      createGoal(title: "Casa própria", targetAmount: "250000.00") {
        goal { id }
      }
    }
    """
    create_response = _graphql(client, create_mutation, token=owner_token)
    assert create_response.status_code == 200
    create_body = create_response.get_json()
    goal_id = create_body["data"]["createGoal"]["goal"]["id"]

    get_query = """
    query GetGoal($goalId: UUID!) {
      goal(goalId: $goalId) {
        id
      }
    }
    """
    forbidden = _graphql(client, get_query, {"goalId": goal_id}, token=other_token)
    assert forbidden.status_code == 200
    body = forbidden.get_json()
    assert body["data"]["goal"] is None
    assert body["errors"][0]["extensions"]["code"] == "FORBIDDEN"
