import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

# Import de notre workflow et de notre activité
from workflows.activities import generate_strategy_activity
from workflows.workflow import StrategyWorkflow

async def main():
    # 1. Connexion au serveur Temporal local
    client = await Client.connect("localhost:7233")

    # 2. Configuration du Worker
    # Il écoute la file "strategy-task-queue"
    worker = Worker(
        client,
        task_queue="strategy-task-queue",
        workflows=[StrategyWorkflow],
        activities=[generate_strategy_activity],
    )

    print("👷 Worker démarré ! Il attend des tâches de l'IA...")
    await worker.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nWorker arrêté.")