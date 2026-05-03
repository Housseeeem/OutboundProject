import asyncio

def run_async(coro):
    """
    Simple async runner - we're moving away from this but keep for compatibility
    """
    try:
        loop = asyncio.get_running_loop()
        # If we're in an async context, this shouldn't be called
        raise RuntimeError("run_async called from async context")
    except RuntimeError:
        pass
    
    return asyncio.run(coro)