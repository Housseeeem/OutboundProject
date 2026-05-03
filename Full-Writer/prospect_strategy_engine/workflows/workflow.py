from datetime import timedelta
from temporalio import workflow

# On autorise l'import des activités dans l'environnement sécurisé de Temporal
with workflow.unsafe.imports_passed_through():
    from workflows.activities import generate_strategy_activity

@workflow.defn
class StrategyWorkflow:
    @workflow.run
    async def run(self, input_data: dict) -> dict:
        """
        C'est le chef d'orchestre qui lance l'activité de génération.
        """
        return await workflow.execute_activity(
            generate_strategy_activity,
            input_data,
            start_to_close_timeout=timedelta(minutes=5), # On laisse 5 min à l'IA pour répondre
        )