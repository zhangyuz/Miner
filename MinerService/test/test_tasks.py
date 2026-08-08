import asyncio
from unittest import TestCase
from unittest.mock import MagicMock, patch

from minerservice import tasks
from minerservice.api.v1 import tasks as api_tasks


class DailyUpdatesTaskTestCase(TestCase):

    @patch('minerservice.tasks.chain')
    def test_daily_chain_skips_automatic_wedge_pop_analysis(self, mock_chain):
        workflow = MagicMock()
        mock_chain.return_value = workflow

        self.assertTrue(tasks.run_us_daily_updates_task.run())

        task_names = [signature.task for signature in mock_chain.call_args.args]
        self.assertIn(tasks.update_wedge_pop_for_index_task.name, task_names)
        self.assertNotIn(tasks.analyze_wedge_pop_task.name, task_names)
        wedge_pop_index = task_names.index(tasks.update_wedge_pop_for_index_task.name)
        self.assertEqual(
            task_names[wedge_pop_index + 1],
            tasks.update_us_idxs_daily_info_task.name,
        )
        workflow.apply_async.assert_called_once_with()

    @patch('minerservice.api.v1.tasks.analyze_wedge_pop_task.delay')
    def test_manual_wedge_pop_analysis_remains_available(self, mock_delay):
        self.assertEqual(asyncio.run(api_tasks.analyze_wedge_pop()), 'GOOD')
        mock_delay.assert_called_once_with()
