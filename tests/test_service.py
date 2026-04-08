"""Tests for the service startup logic."""

from unittest.mock import patch

from investment_researcher.service import run_service


class TestServiceStartup:
    @patch("investment_researcher.service._serve_deployments")
    @patch("investment_researcher.flows.sec_data.seed_flow")
    @patch("investment_researcher.service.configure_edgar")
    @patch("investment_researcher.service.initialize_state_db")
    @patch("investment_researcher.service.initialize_db")
    @patch("investment_researcher.service.is_db_empty", return_value=False)
    @patch("investment_researcher.service.is_storage_empty", return_value=False)
    def test_skips_seed_when_existing_data(
        self,
        mock_storage_empty,
        mock_db_empty,
        mock_initialize_db,
        mock_initialize_state_db,
        mock_configure_edgar,
        mock_seed_flow,
        mock_serve_deployments,
    ):
        run_service()

        mock_storage_empty.assert_called_once()
        mock_db_empty.assert_called_once()
        mock_seed_flow.assert_not_called()
        mock_serve_deployments.assert_called_once()

    @patch("investment_researcher.service._serve_deployments")
    @patch("investment_researcher.flows.sec_data.seed_flow")
    @patch("investment_researcher.service.configure_edgar")
    @patch("investment_researcher.service.initialize_state_db")
    @patch("investment_researcher.service.initialize_db")
    @patch("investment_researcher.service.is_db_empty", return_value=True)
    @patch("investment_researcher.service.is_storage_empty", return_value=False)
    def test_runs_seed_when_db_empty(
        self,
        mock_storage_empty,
        mock_db_empty,
        mock_initialize_db,
        mock_initialize_state_db,
        mock_configure_edgar,
        mock_seed_flow,
        mock_serve_deployments,
    ):
        run_service()

        mock_storage_empty.assert_called_once()
        mock_db_empty.assert_called_once()
        mock_seed_flow.assert_called_once()
        mock_serve_deployments.assert_called_once()

    @patch("investment_researcher.service._serve_deployments")
    @patch("investment_researcher.flows.sec_data.seed_flow")
    @patch("investment_researcher.service.configure_edgar")
    @patch("investment_researcher.service.initialize_state_db")
    @patch("investment_researcher.service.initialize_db")
    @patch("investment_researcher.service.is_db_empty", return_value=False)
    @patch("investment_researcher.service.is_storage_empty", return_value=False)
    @patch("investment_researcher.service.FORCE_SEED", True)
    def test_force_seed_bypasses_state_check(
        self,
        mock_storage_empty,
        mock_db_empty,
        mock_initialize_db,
        mock_initialize_state_db,
        mock_configure_edgar,
        mock_seed_flow,
        mock_serve_deployments,
    ):
        run_service()

        # seed runs even though both storage and db report non-empty
        mock_seed_flow.assert_called_once()
        mock_serve_deployments.assert_called_once()
