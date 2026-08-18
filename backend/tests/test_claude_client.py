import json
from unittest.mock import MagicMock, patch
import pytest
from app.services import claude_client
from app.services.claude_client import analyze_lease, analyze_financial_filing

_FINDING_OK = {"summary": "Nothing concerning here.", "quote": None, "action": "No action needed."}

VALID_RESPONSE = {
    "intro": "This lease looks mostly standard with one concern.",
    "verdict": "review",
    "keyNumbers": {
        "monthlyRent": "$1,500/month",
        "securityDeposit": "$3,000",
        "leaseLength": "12 months",
        "lateFee": None,
        "earlyTerminationFee": None,
    },
    "categories": [
        {
            "name": "Auto-Renewal Clauses",
            "severity": "red",
            "findings": [
                {
                    "summary": "Auto-renews without notice.",
                    "quote": "This lease shall automatically renew for an equal term.",
                    "action": "Ask landlord to add a 60-day written notice requirement to opt out.",
                }
            ],
        },
        {"name": "Deposit Conditions", "severity": "green", "findings": [_FINDING_OK]},
        {
            "name": "Unusual Fees",
            "severity": "yellow",
            "findings": [
                {
                    "summary": "$25/month admin fee is uncommon.",
                    "quote": "Tenant shall pay a monthly administrative fee of $25.",
                    "action": "Ask the landlord to remove or justify this fee.",
                }
            ],
        },
        {"name": "Missing Standard Clauses", "severity": "green", "findings": [_FINDING_OK]},
    ],
}


def _mock_claude(response_text: str):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.with_options.return_value = mock_client
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_analyze_lease_returns_parsed_dict():
    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude(json.dumps(VALID_RESPONSE))
        result = analyze_lease("Sample lease text " * 50)
    assert result["intro"] == VALID_RESPONSE["intro"]
    assert len(result["categories"]) == 4


def test_analyze_lease_retries_on_malformed_json():
    valid_json = json.dumps(VALID_RESPONSE)
    call_count = 0

    def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        text = "not json" if call_count == 1 else valid_json
        msg = MagicMock()
        msg.content = [MagicMock(text=text)]
        return msg

    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create.side_effect = side_effect
        MockAnthropic.return_value = mock_client
        result = analyze_lease("Sample lease text " * 50)

    assert call_count == 2
    assert result["intro"] == VALID_RESPONSE["intro"]


def test_analyze_lease_raises_after_two_malformed_responses():
    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude("not valid json at all")
        with pytest.raises(ValueError, match="invalid JSON"):
            analyze_lease("Sample lease text " * 50)


def test_analyze_lease_strips_markdown_fences():
    fenced = f"```json\n{json.dumps(VALID_RESPONSE)}\n```"
    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude(fenced)
        result = analyze_lease("Sample lease text " * 50)
    assert result["intro"] == VALID_RESPONSE["intro"]


_FILING_FINDING_OK = {"summary": "Nothing material to report.", "citation": None, "confidence": "high"}

VALID_FILING_RESPONSE = {
    "intro": "This filing shows steady revenue growth with one notable litigation risk.",
    "verdict": "review",
    "keyMetrics": {
        "totalRevenue": "$4.2B",
        "netIncome": "$310M",
        "totalDebt": "$1.1B",
        "cashAndEquivalents": "$600M",
        "operatingCashFlow": "$450M",
    },
    "categories": [
        {
            "name": "Risk Factors",
            "severity": "yellow",
            "findings": [
                {
                    "summary": "Pending litigation could materially affect results.",
                    "citation": {"quote": "The Company is subject to a pending lawsuit.", "page": 14},
                    "confidence": "medium",
                }
            ],
        },
        {"name": "MD&A / Financial Performance", "severity": "green", "findings": [_FILING_FINDING_OK]},
        {"name": "Liquidity & Capital Resources", "severity": "green", "findings": [_FILING_FINDING_OK]},
        {"name": "Related-Party Transactions", "severity": "green", "findings": [_FILING_FINDING_OK]},
        {"name": "Legal Proceedings & Contingencies", "severity": "green", "findings": [_FILING_FINDING_OK]},
        {"name": "Accounting Policy Changes", "severity": "green", "findings": [_FILING_FINDING_OK]},
    ],
}


def test_analyze_financial_filing_returns_parsed_dict():
    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude(json.dumps(VALID_FILING_RESPONSE))
        result = analyze_financial_filing("Sample filing text " * 50)
    assert result["intro"] == VALID_FILING_RESPONSE["intro"]
    assert len(result["categories"]) == 6


def test_analyze_financial_filing_retries_on_malformed_json():
    valid_json = json.dumps(VALID_FILING_RESPONSE)
    call_count = 0

    def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        text = "not json" if call_count == 1 else valid_json
        msg = MagicMock()
        msg.content = [MagicMock(text=text)]
        return msg

    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create.side_effect = side_effect
        MockAnthropic.return_value = mock_client
        result = analyze_financial_filing("Sample filing text " * 50)

    assert call_count == 2
    assert result["intro"] == VALID_FILING_RESPONSE["intro"]


def test_analyze_financial_filing_raises_after_two_malformed_responses():
    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude("not valid json at all")
        with pytest.raises(ValueError, match="invalid JSON"):
            analyze_financial_filing("Sample filing text " * 50)


def test_analyze_financial_filing_strips_markdown_fences():
    fenced = f"```json\n{json.dumps(VALID_FILING_RESPONSE)}\n```"
    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value = _mock_claude(fenced)
        result = analyze_financial_filing("Sample filing text " * 50)
    assert result["intro"] == VALID_FILING_RESPONSE["intro"]


def test_analyze_financial_filing_passes_bounded_timeout_and_disables_sdk_retries():
    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic:
        mock_client = _mock_claude(json.dumps(VALID_FILING_RESPONSE))
        MockAnthropic.return_value = mock_client
        analyze_financial_filing("Sample filing text " * 50)

    assert mock_client.with_options.call_count == 1
    _, kwargs = mock_client.with_options.call_args
    assert kwargs["max_retries"] == 0
    assert 0 < kwargs["timeout"] <= claude_client.FILING_CLAUDE_BUDGET_SECONDS


def test_analyze_financial_filing_raises_timeout_error_when_budget_exhausted():
    """If the first (malformed-JSON) attempt eats the whole budget, don't attempt a second
    call — raise a clean TimeoutError instead of letting the caller hang indefinitely."""
    with patch("app.services.claude_client.anthropic.Anthropic") as MockAnthropic, patch(
        "app.services.claude_client.time.monotonic"
    ) as mock_monotonic:
        # 1 call to set the deadline, then 1 remaining-time check per attempt reached.
        mock_monotonic.side_effect = [0, 0, 10_000]
        mock_client = _mock_claude("not valid json at all")
        MockAnthropic.return_value = mock_client

        with pytest.raises(TimeoutError, match="budget"):
            analyze_financial_filing("Sample filing text " * 50)

    mock_client.messages.create.assert_called_once()
