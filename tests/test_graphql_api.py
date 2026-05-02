import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict
from uuid import UUID

from app.application.services.email_confirmation_service import (
    EMAIL_CONFIRMATION_INVALID_TOKEN_MESSAGE,
    EMAIL_CONFIRMATION_NEUTRAL_MESSAGE,
    EMAIL_CONFIRMATION_SUCCESS_MESSAGE,
)
from app.application.services.password_reset_service import (
    PASSWORD_RESET_INVALID_TOKEN_MESSAGE,
    PASSWORD_RESET_NEUTRAL_MESSAGE,
    PASSWORD_RESET_SUCCESS_MESSAGE,
)
from app.extensions.database import db
from app.graphql.types import UserType
from app.models.account import Account
from app.models.credit_card import CreditCard
from app.models.tag import Tag
from app.models.user import User


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


def _register_and_login_graphql(client) -> str:
    suffix = "graphql-user"
    register_mutation = """
    mutation Register($name: String!, $email: String!, $password: String!) {
      registerUser(name: $name, email: $email, password: $password) {
        message
        user { id name email }
      }
    }
    """
    register_response = _graphql(
        client,
        register_mutation,
        {
            "name": suffix,
            "email": f"{suffix}@email.com",
            "password": "StrongPass@123",
        },
    )
    assert register_response.status_code == 200
    register_body = register_response.get_json()
    assert "errors" not in register_body
    assert (
        register_body["data"]["registerUser"]["message"] == "User created successfully"
    )

    login_mutation = """
    mutation Login($email: String!, $password: String!) {
      login(email: $email, password: $password) {
        message
        token
        user { id name email }
      }
    }
    """
    login_response = _graphql(
        client,
        login_mutation,
        {"email": f"{suffix}@email.com", "password": "StrongPass@123"},
    )
    assert login_response.status_code == 200
    login_body = login_response.get_json()
    assert "errors" not in login_body
    token = login_body["data"]["login"]["token"]
    assert token
    return token


def _get_user_id_by_email(app: Any, email: str) -> UUID:
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user is not None
        return UUID(str(user.id))


def test_graphql_register_login_and_me(client) -> None:
    token = _register_and_login_graphql(client)

    me_query = """
    query Me {
      me {
        id
        name
        email
      }
    }
    """
    response = _graphql(client, me_query, token=token)
    assert response.status_code == 200
    body = response.get_json()
    assert "errors" not in body
    assert body["data"]["me"]["email"] == "graphql-user@email.com"


def test_graphql_me_remains_user_context_only(client) -> None:
    token = _register_and_login_graphql(client)

    response = _graphql(
        client, "query Me { me { id name email monthlyIncome } }", token=token
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "errors" not in body
    assert body["data"]["me"]["email"] == "graphql-user@email.com"
    assert "wallet" not in UserType._meta.fields
    assert "transactions" not in UserType._meta.fields


def test_graphql_forgot_password_is_neutral(client) -> None:
    mutation = """
    mutation ForgotPassword($email: String!) {
      forgotPassword(email: $email) {
        message
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {"email": "unknown-user@email.com"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "errors" not in body
    assert body["data"]["forgotPassword"]["message"] == PASSWORD_RESET_NEUTRAL_MESSAGE


def test_graphql_reset_password_with_invalid_token_returns_public_validation_error(
    client,
) -> None:
    mutation = """
    mutation ResetPassword($token: String!, $newPassword: String!) {
      resetPassword(token: $token, newPassword: $newPassword) {
        message
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {
            "token": "invalid-token-value-with-sufficient-length-123456",
            "newPassword": "NovaSenha@123",
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "data" in body
    assert body["data"]["resetPassword"] is None
    assert body["errors"][0]["extensions"]["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["message"] == PASSWORD_RESET_INVALID_TOKEN_MESSAGE


def test_graphql_reset_password_flow_allows_new_credentials(client) -> None:
    suffix = "graphql-reset-user"
    register_mutation = """
    mutation Register($name: String!, $email: String!, $password: String!) {
      registerUser(name: $name, email: $email, password: $password) {
        message
      }
    }
    """
    email = f"{suffix}@email.com"
    register_response = _graphql(
        client,
        register_mutation,
        {
            "name": suffix,
            "email": email,
            "password": "StrongPass@123",
        },
    )
    assert register_response.status_code == 200
    assert "errors" not in register_response.get_json()

    forgot_mutation = """
    mutation ForgotPassword($email: String!) {
      forgotPassword(email: $email) {
        message
      }
    }
    """
    forgot_response = _graphql(client, forgot_mutation, {"email": email})
    assert forgot_response.status_code == 200
    forgot_body = forgot_response.get_json()
    assert "errors" not in forgot_body
    assert (
        forgot_body["data"]["forgotPassword"]["message"]
        == PASSWORD_RESET_NEUTRAL_MESSAGE
    )

    outbox = client.application.extensions.get("password_reset_outbox", [])
    assert isinstance(outbox, list)
    token = outbox[0]["token"]

    reset_mutation = """
    mutation ResetPassword($token: String!, $newPassword: String!) {
      resetPassword(token: $token, newPassword: $newPassword) {
        message
      }
    }
    """
    reset_response = _graphql(
        client,
        reset_mutation,
        {"token": token, "newPassword": "NovaSenha@123"},
    )
    assert reset_response.status_code == 200
    reset_body = reset_response.get_json()
    assert "errors" not in reset_body
    assert (
        reset_body["data"]["resetPassword"]["message"] == PASSWORD_RESET_SUCCESS_MESSAGE
    )

    login_mutation = """
    mutation Login($email: String!, $password: String!) {
      login(email: $email, password: $password) {
        message
        token
      }
    }
    """
    old_login_response = _graphql(
        client,
        login_mutation,
        {"email": email, "password": "StrongPass@123"},
    )
    assert old_login_response.status_code == 200
    old_login_body = old_login_response.get_json()
    assert old_login_body["data"]["login"] is None
    assert old_login_body["errors"][0]["extensions"]["code"] == "UNAUTHORIZED"

    new_login_response = _graphql(
        client,
        login_mutation,
        {"email": email, "password": "NovaSenha@123"},
    )
    assert new_login_response.status_code == 200
    new_login_body = new_login_response.get_json()
    assert "errors" not in new_login_body
    assert new_login_body["data"]["login"]["token"]


def test_graphql_resend_confirmation_is_neutral(client) -> None:
    mutation = """
    mutation ResendConfirmation($email: String!) {
      resendConfirmationEmail(email: $email) {
        message
      }
    }
    """
    response = _graphql(client, mutation, {"email": "unknown-user@email.com"})
    assert response.status_code == 200
    body = response.get_json()
    assert "errors" not in body
    assert (
        body["data"]["resendConfirmationEmail"]["message"]
        == EMAIL_CONFIRMATION_NEUTRAL_MESSAGE
    )


def test_graphql_confirm_email_flow(client) -> None:
    suffix = "graphql-confirm-user"
    register_mutation = """
    mutation Register($name: String!, $email: String!, $password: String!) {
      registerUser(name: $name, email: $email, password: $password) {
        message
      }
    }
    """
    email = f"{suffix}@email.com"
    register_response = _graphql(
        client,
        register_mutation,
        {
            "name": suffix,
            "email": email,
            "password": "StrongPass@123",
        },
    )
    assert register_response.status_code == 200
    assert "errors" not in register_response.get_json()

    outbox = client.application.extensions.get("email_confirmation_outbox", [])
    assert isinstance(outbox, list)
    token = outbox[0]["token"]

    confirm_mutation = """
    mutation ConfirmEmail($token: String!) {
      confirmEmail(token: $token) {
        message
      }
    }
    """
    confirm_response = _graphql(client, confirm_mutation, {"token": token})
    assert confirm_response.status_code == 200
    confirm_body = confirm_response.get_json()
    assert "errors" not in confirm_body
    assert (
        confirm_body["data"]["confirmEmail"]["message"]
        == EMAIL_CONFIRMATION_SUCCESS_MESSAGE
    )


def test_graphql_confirm_email_with_invalid_token_returns_public_validation_error(
    client,
) -> None:
    mutation = """
    mutation ConfirmEmail($token: String!) {
      confirmEmail(token: $token) {
        message
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {"token": "invalid-token-value-with-sufficient-length-123456"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["data"]["confirmEmail"] is None
    assert body["errors"][0]["extensions"]["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["message"] == EMAIL_CONFIRMATION_INVALID_TOKEN_MESSAGE


def test_graphql_transactions_summary_and_dashboard(app, client) -> None:
    token = _register_and_login_graphql(client)
    due_date = date.today().isoformat()
    user_id = _get_user_id_by_email(app, "graphql-user@email.com")

    with app.app_context():
        household_tag = Tag(user_id=user_id, name="Casa")
        operating_account = Account(user_id=user_id, name="Conta principal")
        travel_card = CreditCard(user_id=user_id, name="Cartao viagem")
        db.session.add_all([household_tag, operating_account, travel_card])
        db.session.commit()
        household_tag_id = str(household_tag.id)
        operating_account_id = str(operating_account.id)
        travel_card_id = str(travel_card.id)

    create_mutation = """
    mutation CreateTx(
      $title: String!,
      $amount: String!,
      $type: TransactionType!,
      $dueDate: String!,
      $tagId: UUID,
      $accountId: UUID,
      $creditCardId: UUID
    ) {
      createTransaction(
        title: $title,
        amount: $amount,
        type: $type,
        dueDate: $dueDate,
        tagId: $tagId,
        accountId: $accountId,
        creditCardId: $creditCardId
      ) {
        message
        items { id title type amount dueDate tagId accountId creditCardId }
      }
    }
    """
    expense_response = _graphql(
        client,
        create_mutation,
        {
            "title": "Conta de luz",
            "amount": "150.00",
            "type": "EXPENSE",
            "dueDate": due_date,
            "tagId": household_tag_id,
            "accountId": operating_account_id,
            "creditCardId": travel_card_id,
        },
        token=token,
    )
    assert expense_response.status_code == 200
    assert "errors" not in expense_response.get_json()

    income_response = _graphql(
        client,
        create_mutation,
        {
            "title": "Freelance",
            "amount": "500.00",
            "type": "INCOME",
            "dueDate": due_date,
        },
        token=token,
    )
    assert income_response.status_code == 200
    assert "errors" not in income_response.get_json()

    overdue_response = _graphql(
        client,
        create_mutation,
        {
            "title": "Conta atrasada",
            "amount": "70.00",
            "type": "EXPENSE",
            "dueDate": (date.today() - timedelta(days=1)).isoformat(),
        },
        token=token,
    )
    assert overdue_response.status_code == 200
    assert "errors" not in overdue_response.get_json()

    list_query = """
    query ListTx($tagId: UUID!, $accountId: UUID!, $creditCardId: UUID!) {
      transactions(
        page: 1,
        perPage: 10,
        tagId: $tagId,
        accountId: $accountId,
        creditCardId: $creditCardId
      ) {
        items { id title type amount }
        pagination { total page perPage }
      }
    }
    """
    list_response = _graphql(
        client,
        list_query,
        {
            "tagId": household_tag_id,
            "accountId": operating_account_id,
            "creditCardId": travel_card_id,
        },
        token=token,
    )
    assert list_response.status_code == 200
    list_body = list_response.get_json()
    assert "errors" not in list_body
    assert list_body["data"]["transactions"]["pagination"]["total"] == 1
    assert list_body["data"]["transactions"]["items"][0]["title"] == "Conta de luz"

    month_ref = date.today().strftime("%Y-%m")
    summary_query = """
    query Summary($month: String!) {
      transactionSummary(month: $month, page: 1, perPage: 10) {
        month
        incomeTotal
        expenseTotal
        pagination { total }
      }
    }
    """
    summary_response = _graphql(
        client, summary_query, {"month": month_ref}, token=token
    )
    assert summary_response.status_code == 200
    summary_body = summary_response.get_json()
    assert "errors" not in summary_body
    assert summary_body["data"]["transactionSummary"]["month"] == month_ref

    dashboard_query = """
    query Dashboard($month: String!) {
      dashboardOverview(month: $month) {
        month
        totals { incomeTotal expenseTotal balance }
        counts { totalTransactions incomeTransactions expenseTransactions }
      }
      transactionDashboard(month: $month) {
        month
        totals { incomeTotal expenseTotal balance }
      }
    }
    """
    dashboard_response = _graphql(
        client, dashboard_query, {"month": month_ref}, token=token
    )
    assert dashboard_response.status_code == 200
    dashboard_body = dashboard_response.get_json()
    assert "errors" not in dashboard_body
    assert dashboard_body["data"]["dashboardOverview"]["month"] == month_ref
    assert dashboard_body["data"]["transactionDashboard"]["month"] == month_ref
    assert (
        dashboard_body["data"]["dashboardOverview"]["totals"]["expenseTotal"]
        == dashboard_body["data"]["transactionDashboard"]["totals"]["expenseTotal"]
    )

    due_range_query = """
    query DueRange($startDate: String!, $endDate: String!) {
      transactionDueRange(
        startDate: $startDate,
        endDate: $endDate,
        page: 1,
        perPage: 10,
        orderBy: "overdue_first"
      ) {
        items { title type dueDate }
        counts { totalTransactions incomeTransactions expenseTransactions }
        pagination { total page perPage }
      }
    }
    """
    due_range_response = _graphql(
        client,
        due_range_query,
        {
            "startDate": (date.today() - timedelta(days=1)).isoformat(),
            "endDate": date.today().isoformat(),
        },
        token=token,
    )
    assert due_range_response.status_code == 200
    due_range_body = due_range_response.get_json()
    assert "errors" not in due_range_body
    due_payload = due_range_body["data"]["transactionDueRange"]
    assert due_payload["counts"]["totalTransactions"] == 3
    assert due_payload["counts"]["incomeTransactions"] == 1
    assert due_payload["counts"]["expenseTransactions"] == 2
    assert due_payload["items"][0]["title"] == "Conta atrasada"

    first_transaction_id = list_body["data"]["transactions"]["items"][0]["id"]
    transaction_query = """
    query Transaction($transactionId: UUID!) {
      transaction(transactionId: $transactionId) {
        id
        title
        amount
        source
      }
    }
    """
    transaction_response = _graphql(
        client,
        transaction_query,
        {"transactionId": first_transaction_id},
        token=token,
    )
    assert transaction_response.status_code == 200
    transaction_body = transaction_response.get_json()
    assert "errors" not in transaction_body
    assert transaction_body["data"]["transaction"]["id"] == first_transaction_id

    update_mutation = """
    mutation UpdateTx(
      $transactionId: UUID!,
      $title: String!,
      $status: TransactionStatus!,
      $paidAt: String!
    ) {
      updateTransaction(
        transactionId: $transactionId,
        title: $title,
        status: $status,
        paidAt: $paidAt
      ) {
        message
        transaction { id title status paidAt }
      }
    }
    """
    update_response = _graphql(
        client,
        update_mutation,
        {
            "transactionId": first_transaction_id,
            "title": "Conta de luz atualizada",
            "status": "PAID",
            "paidAt": "2026-03-01T10:00:00+00:00",
        },
        token=token,
    )
    assert update_response.status_code == 200
    update_body = update_response.get_json()
    assert "errors" not in update_body
    assert update_body["data"]["updateTransaction"]["transaction"]["title"] == (
        "Conta de luz atualizada"
    )
    assert update_body["data"]["updateTransaction"]["transaction"]["status"] == "paid"


def test_graphql_transactions_supports_legacy_summary_and_due_range_arguments(
    client,
) -> None:
    token = _register_and_login_graphql(client)
    month_ref = date.today().strftime("%Y-%m")
    create_mutation = """
    mutation CreateTx($dueDate: String!) {
      createTransaction(
        title: "Conta legado",
        amount: "50.00",
        type: EXPENSE,
        dueDate: $dueDate
      ) {
        items { id }
      }
    }
    """
    create_response = _graphql(
        client,
        create_mutation,
        {"dueDate": date.today().isoformat()},
        token=token,
    )
    assert create_response.status_code == 200
    assert "errors" not in create_response.get_json()

    summary_query = """
    query LegacySummary($month: String!) {
      transactionSummary(month: $month, page: 1, pageSize: 10) {
        month
        pagination { total perPage }
      }
    }
    """
    summary_response = _graphql(
        client,
        summary_query,
        {"month": month_ref},
        token=token,
    )
    assert summary_response.status_code == 200
    summary_body = summary_response.get_json()
    assert "errors" not in summary_body
    assert summary_body["data"]["transactionSummary"]["pagination"]["perPage"] == 10

    due_range_query = """
    query LegacyDueRange($initialDate: String!, $finalDate: String!) {
      transactionDueRange(
        initialDate: $initialDate,
        finalDate: $finalDate,
        page: 1,
        perPage: 10
      ) {
        pagination { total }
      }
    }
    """
    due_range_response = _graphql(
        client,
        due_range_query,
        {
            "initialDate": date.today().isoformat(),
            "finalDate": date.today().isoformat(),
        },
        token=token,
    )
    assert due_range_response.status_code == 200
    due_range_body = due_range_response.get_json()
    assert "errors" not in due_range_body
    assert due_range_body["data"]["transactionDueRange"]["pagination"]["total"] == 1


def test_graphql_wallet_and_ticker_queries_mutations(client) -> None:
    token = _register_and_login_graphql(client)
    add_wallet_mutation = """
    mutation AddWallet {
      addWalletEntry(
        name: "Reserva",
        value: 1000,
        registerDate: "2026-02-09",
        shouldBeOnWallet: true
      ) {
        item { id name value registerDate shouldBeOnWallet assetClass }
      }
    }
    """
    wallet_response = _graphql(client, add_wallet_mutation, token=token)
    assert wallet_response.status_code == 200
    wallet_body = wallet_response.get_json()
    assert "errors" not in wallet_body
    assert wallet_body["data"]["addWalletEntry"]["item"]["name"] == "Reserva"
    assert wallet_body["data"]["addWalletEntry"]["item"]["assetClass"] == "custom"
    investment_id = wallet_body["data"]["addWalletEntry"]["item"]["id"]

    add_operation_mutation = """
    mutation AddOperation($investmentId: UUID!, $executedAt: String!) {
      addInvestmentOperation(
        investmentId: $investmentId,
        operationType: "buy",
        quantity: "3",
        unitPrice: "22.50",
        fees: "1.20",
        executedAt: $executedAt
      ) {
        message
        item { id operationType quantity unitPrice fees }
      }
    }
    """
    add_operation_response = _graphql(
        client,
        add_operation_mutation,
        {"investmentId": investment_id, "executedAt": "2026-02-09"},
        token=token,
    )
    assert add_operation_response.status_code == 200
    add_operation_body = add_operation_response.get_json()
    assert "errors" not in add_operation_body
    assert add_operation_body["data"]["addInvestmentOperation"]["item"]["quantity"] == (
        "3.000000"
    )

    operations_query = """
    query Operations($investmentId: UUID!, $date: String!) {
      investmentOperations(investmentId: $investmentId, page: 1, perPage: 10) {
        items { id operationType quantity unitPrice }
        pagination { total page perPage }
      }
      investmentOperationSummary(investmentId: $investmentId) {
        totalOperations
        buyOperations
        sellOperations
        netQuantity
      }
      investmentPosition(investmentId: $investmentId) {
        totalOperations
        buyOperations
        sellOperations
        totalBuyQuantity
        totalSellQuantity
        currentQuantity
        currentCostBasis
        averageCost
      }
      investmentInvestedAmount(investmentId: $investmentId, date: $date) {
        date
        totalOperations
        buyOperations
        sellOperations
        buyAmount
        sellAmount
        netInvestedAmount
      }
    }
    """
    operations_response = _graphql(
        client,
        operations_query,
        {"investmentId": investment_id, "date": "2026-02-09"},
        token=token,
    )
    assert operations_response.status_code == 200
    operations_body = operations_response.get_json()
    assert "errors" not in operations_body
    assert operations_body["data"]["investmentOperations"]["pagination"]["total"] == 1
    assert operations_body["data"]["investmentOperationSummary"]["buyOperations"] == 1
    assert (
        operations_body["data"]["investmentPosition"]["currentQuantity"] == "3.000000"
    )
    assert Decimal(
        operations_body["data"]["investmentInvestedAmount"]["netInvestedAmount"]
    ) == Decimal("68.7")

    wallet_query = """
    query WalletEntries {
      walletEntries(page: 1, perPage: 10) {
        items { id name registerDate shouldBeOnWallet }
        pagination { total page perPage }
      }
    }
    """
    wallet_list_response = _graphql(client, wallet_query, token=token)
    assert wallet_list_response.status_code == 200
    wallet_list_body = wallet_list_response.get_json()
    assert "errors" not in wallet_list_body
    assert wallet_list_body["data"]["walletEntries"]["pagination"]["total"] >= 1

    valuation_query = """
    query Valuation($investmentId: UUID!) {
      investmentValuation(investmentId: $investmentId) {
        investmentId
        name
        assetClass
        valuationSource
        investedAmount
        currentValue
        profitLossAmount
        profitLossPercent
      }
      portfolioValuation {
        summary {
          totalInvestments
          totalInvestedAmount
          totalCurrentValue
          totalProfitLoss
          totalProfitLossPercent
        }
      }
      portfolioValuationHistory(startDate: "2026-02-09", finalDate: "2026-02-09") {
        summary {
          startDate
          endDate
          totalPoints
          totalNetInvestedAmount
          finalCumulativeNetInvested
        }
        items {
          date
          totalOperations
          netInvestedAmount
          cumulativeNetInvested
        }
      }
    }
    """
    valuation_response = _graphql(
        client,
        valuation_query,
        {"investmentId": investment_id},
        token=token,
    )
    assert valuation_response.status_code == 200
    valuation_body = valuation_response.get_json()
    assert "errors" not in valuation_body
    assert valuation_body["data"]["investmentValuation"]["valuationSource"] == (
        "manual_value"
    )
    assert valuation_body["data"]["investmentValuation"]["assetClass"] == "custom"
    assert Decimal(valuation_body["data"]["investmentValuation"]["investedAmount"]) == (
        Decimal("1000")
    )
    assert (
        valuation_body["data"]["portfolioValuation"]["summary"]["totalInvestments"] >= 1
    )
    assert (
        valuation_body["data"]["portfolioValuationHistory"]["summary"]["totalPoints"]
        == 1
    )
    assert (
        valuation_body["data"]["portfolioValuationHistory"]["items"][0][
            "totalOperations"
        ]
        == 1
    )

    fixed_income_mutation = """
    mutation AddFixedIncomeWallet {
      addWalletEntry(
        name: "CDB",
        value: 1000,
        quantity: 1,
        assetClass: CDB,
        annualRate: 12,
        registerDate: "2026-01-01",
        shouldBeOnWallet: true
      ) {
        item { id assetClass annualRate }
      }
    }
    """
    fixed_income_response = _graphql(client, fixed_income_mutation, token=token)
    assert fixed_income_response.status_code == 200
    fixed_income_body = fixed_income_response.get_json()
    assert "errors" not in fixed_income_body
    fixed_income_id = fixed_income_body["data"]["addWalletEntry"]["item"]["id"]

    fixed_income_valuation_query = """
    query FixedIncomeValuation($investmentId: UUID!) {
      investmentValuation(investmentId: $investmentId) {
        assetClass
        valuationSource
        investedAmount
        currentValue
      }
    }
    """
    fixed_income_valuation_response = _graphql(
        client,
        fixed_income_valuation_query,
        {"investmentId": fixed_income_id},
        token=token,
    )
    assert fixed_income_valuation_response.status_code == 200
    fixed_income_valuation_body = fixed_income_valuation_response.get_json()
    assert "errors" not in fixed_income_valuation_body
    assert (
        fixed_income_valuation_body["data"]["investmentValuation"]["assetClass"]
        == "cdb"
    )
    assert (
        fixed_income_valuation_body["data"]["investmentValuation"]["valuationSource"]
        == "fixed_income_projection"
    )

    add_ticker_mutation = """
    mutation AddTicker {
      addTicker(symbol: "PETR4", quantity: 10, type: "stock") {
        item { id symbol quantity type }
      }
    }
    """
    add_ticker_response = _graphql(client, add_ticker_mutation, token=token)
    assert add_ticker_response.status_code == 200
    add_ticker_body = add_ticker_response.get_json()
    assert "errors" not in add_ticker_body
    assert add_ticker_body["data"]["addTicker"]["item"]["symbol"] == "PETR4"

    tickers_query = """
    query Tickers {
      tickers {
        symbol
        quantity
        type
      }
    }
    """
    tickers_response = _graphql(client, tickers_query, token=token)
    assert tickers_response.status_code == 200
    tickers_body = tickers_response.get_json()
    assert "errors" not in tickers_body
    assert len(tickers_body["data"]["tickers"]) == 1

    delete_ticker_mutation = """
    mutation DeleteTicker {
      deleteTicker(symbol: "PETR4") {
        ok
        message
      }
    }
    """
    delete_response = _graphql(client, delete_ticker_mutation, token=token)
    assert delete_response.status_code == 200
    delete_body = delete_response.get_json()
    assert "errors" not in delete_body
    assert delete_body["data"]["deleteTicker"]["ok"] is True


def test_graphql_login_requires_email_argument(client) -> None:
    login_mutation = """
    mutation LoginWithoutPrincipal($password: String!) {
      login(password: $password) {
        message
        token
      }
    }
    """
    response = _graphql(
        client,
        login_mutation,
        {"password": "StrongPass@123"},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert "errors" in body
    assert "argument 'email'" in body["errors"][0]["message"]


def test_graphql_login_rejects_legacy_name_argument(client) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"graphql-name-{suffix}@email.com"
    password = "StrongPass@123"
    register_mutation = """
    mutation Register($name: String!, $email: String!, $password: String!) {
      registerUser(name: $name, email: $email, password: $password) {
        message
      }
    }
    """
    register_response = _graphql(
        client,
        register_mutation,
        {
            "name": f"graphql-name-{suffix}",
            "email": email,
            "password": password,
        },
    )
    assert register_response.status_code == 200

    login_mutation = """
    mutation LoginByName($name: String!, $password: String!) {
      login(name: $name, password: $password) {
        message
        token
      }
    }
    """
    response = _graphql(
        client,
        login_mutation,
        {"name": f"graphql-name-{suffix}", "password": password},
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["errors"]
    assert "Unknown argument 'name'" in body["errors"][0]["message"]


def test_graphql_login_with_blank_email_returns_public_validation_error(client) -> None:
    login_mutation = """
    mutation Login($email: String!, $password: String!) {
      login(email: $email, password: $password) {
        message
        token
      }
    }
    """
    response = _graphql(
        client,
        login_mutation,
        {"email": "   ", "password": "StrongPass@123"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["data"]["login"] is None
    assert body["errors"][0]["extensions"]["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["message"] == "Email is required."


def test_graphql_login_invalid_credentials_returns_public_unauthorized(client) -> None:
    login_mutation = """
    mutation Login($email: String!, $password: String!) {
      login(email: $email, password: $password) {
        message
        token
      }
    }
    """
    response = _graphql(
        client,
        login_mutation,
        {
            "email": f"missing-{uuid.uuid4().hex[:8]}@email.com",
            "password": "WrongPass@123",
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["data"]["login"] is None
    assert body["errors"][0]["extensions"]["code"] == "UNAUTHORIZED"
    assert body["errors"][0]["message"] == "Invalid credentials"


def test_graphql_logout_mutation_success(client) -> None:
    token = _register_and_login_graphql(client)
    logout_mutation = """
    mutation Logout {
      logout {
        ok
        message
      }
    }
    """
    response = _graphql(client, logout_mutation, token=token)
    assert response.status_code == 200
    body = response.get_json()
    assert "errors" not in body
    assert body["data"]["logout"]["ok"] is True
    assert body["data"]["logout"]["message"] == "Logout successful"


def test_graphql_ticker_duplicate_and_delete_not_found(client) -> None:
    token = _register_and_login_graphql(client)
    add_ticker_mutation = """
    mutation AddTicker {
      addTicker(symbol: "ITUB4", quantity: 5, type: "stock") {
        item { id symbol }
      }
    }
    """
    first = _graphql(client, add_ticker_mutation, token=token)
    assert first.status_code == 200
    assert "errors" not in first.get_json()

    duplicate = _graphql(client, add_ticker_mutation, token=token)
    assert duplicate.status_code == 200
    duplicate_body = duplicate.get_json()
    assert "errors" in duplicate_body
    assert duplicate_body["errors"][0]["message"] == "Ticker já adicionado"

    delete_missing_mutation = """
    mutation DeleteMissingTicker {
      deleteTicker(symbol: "MISSING") {
        ok
        message
      }
    }
    """
    delete_missing = _graphql(client, delete_missing_mutation, token=token)
    assert delete_missing.status_code == 200
    delete_missing_body = delete_missing.get_json()
    assert "errors" in delete_missing_body
    assert delete_missing_body["errors"][0]["message"] == "Ticker não encontrado"


def test_create_transaction_rejects_unknown_type_enum_literal(client) -> None:
    """An invalid enum literal must be rejected by the GraphQL parser before
    reaching the resolver — clients can no longer push arbitrary strings
    through type/status, mirroring the REST OneOf validation."""

    token = _register_and_login_graphql(client)
    mutation = """
    mutation CreateTx {
      createTransaction(
        title: "Conta",
        amount: "10.00",
        type: NOT_A_TYPE,
        dueDate: "2026-01-01"
      ) {
        message
      }
    }
    """
    response = _graphql(client, mutation, token=token)
    body = response.get_json()
    assert "errors" in body
    error_message = body["errors"][0]["message"]
    assert "NOT_A_TYPE" in error_message or "TransactionType" in error_message


def test_create_transaction_rejects_unknown_type_via_variable(client) -> None:
    """When the value comes through a typed variable, an unknown enum value
    raises a coercion error at the variable-binding step."""

    token = _register_and_login_graphql(client)
    mutation = """
    mutation CreateTx($type: TransactionType!) {
      createTransaction(
        title: "Conta",
        amount: "10.00",
        type: $type,
        dueDate: "2026-01-01"
      ) {
        message
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        variables={"type": "INVALID"},
        token=token,
    )
    body = response.get_json()
    assert "errors" in body


def test_update_goal_accepts_status_enum_literal(client) -> None:
    """Sanity check for enum coercion: the resolver receives the Python enum
    instance and the service still gets the lowercase string value via
    coerce_enum_kwargs."""

    token = _register_and_login_graphql(client)
    create_mutation = """
    mutation CreateGoal {
      createGoal(title: "Casa", targetAmount: "100000.00") {
        goal { id status }
      }
    }
    """
    create_response = _graphql(client, create_mutation, token=token)
    create_body = create_response.get_json()
    assert "errors" not in create_body, create_body
    goal_id = create_body["data"]["createGoal"]["goal"]["id"]

    update_mutation = """
    mutation UpdateGoal($goalId: UUID!) {
      updateGoal(goalId: $goalId, status: COMPLETED) {
        goal { id status }
      }
    }
    """
    response = _graphql(
        client,
        update_mutation,
        variables={"goalId": goal_id},
        token=token,
    )
    body = response.get_json()
    assert "errors" not in body, body
    assert body["data"]["updateGoal"]["goal"]["status"] == "completed"


def test_add_wallet_entry_rejects_unknown_asset_class(client) -> None:
    token = _register_and_login_graphql(client)
    mutation = """
    mutation AddWallet {
      addWalletEntry(
        name: "Custom",
        assetClass: NOT_A_CLASS,
        registerDate: "2026-01-01",
        shouldBeOnWallet: true
      ) {
        item { id }
      }
    }
    """
    response = _graphql(client, mutation, token=token)
    body = response.get_json()
    assert "errors" in body
