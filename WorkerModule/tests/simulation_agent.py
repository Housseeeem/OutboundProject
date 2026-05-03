import asyncio
import logging
from typing import Any, Dict

import httpx


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

WORKER_API_BASE_URL = "http://localhost:8000"
AGENT_RUNS_ENDPOINT = f"{WORKER_API_BASE_URL}/v1/agent/runs"


async def run_agent_workflow() -> Dict[str, Any]:
    payload = {
        "objective": "Run a full outbound workflow and verify the generated trace.",
        "max_steps": 20,
    }

    timeout = httpx.Timeout(60.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(AGENT_RUNS_ENDPOINT, json=payload)
        response.raise_for_status()
        return response.json()


async def verify_agent_run(run_id: str) -> Dict[str, Any]:
    timeout = httpx.Timeout(30.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{AGENT_RUNS_ENDPOINT}/{run_id}")
        response.raise_for_status()
        return response.json()


async def main() -> None:
    logging.info("Starting API-integrated agent simulation.")
    run_result = await run_agent_workflow()
    logging.info("Run created and executed: %s", run_result)

    run_id = run_result.get("run_id")
    if not run_id:
        logging.error("No run_id returned by API response.")
        return

    run_details = await verify_agent_run(run_id)
    logging.info("Persisted run details: %s", run_details)


if __name__ == "__main__":
    asyncio.run(main())
