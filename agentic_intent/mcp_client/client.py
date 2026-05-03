import asyncio
import threading
from typing import Optional, Dict, Any
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.lock = asyncio.Lock()
        self._loop = None

    async def connect(self, server_script_path: str):
        print(f" Starting MCP server: {server_script_path}")

        server_params = StdioServerParameters(
            command="python",
            args=[server_script_path],
            env=None
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )

        print(" Transport created")

        self.stdio, self.write = stdio_transport

        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        print(" Session created")

        await self.session.initialize()
        
        # Store the event loop this session was created in
        self._loop = asyncio.get_running_loop()

        print(" Session initialized")

        tools = await self.session.list_tools()
        print(" Connected MCP tools:", [t.name for t in tools.tools])

    async def call_tool(self, tool_name: str, args: Dict[str, Any]):
        print(f"[MCPClient.call_tool] Called from thread: {threading.current_thread().name}")
        print(f"[MCPClient.call_tool] Tool: {tool_name}, Args: {args}")
        
        async with self.lock:
            print(f"[MCPClient.call_tool] Lock acquired, calling session.call_tool...")
            result = await self.session.call_tool(tool_name, args)
            print(f"[MCPClient.call_tool] call_tool completed")
            return result.content

    def call_tool_sync(self, tool_name: str, args: Dict[str, Any]):
        """Synchronous wrapper for call_tool that can be called from any thread"""
        print(f"[MCPClient.call_tool_sync] Called from thread: {threading.current_thread().name}")
        print(f"[MCPClient.call_tool_sync] Tool: {tool_name}, Args: {args}")
        
        if self._loop is None:
            raise RuntimeError("Client not connected. Call connect() first.")
        
        # Schedule the async call in the main event loop and wait for result
        future = asyncio.run_coroutine_threadsafe(
            self.call_tool(tool_name, args),
            self._loop
        )
        
        # Wait for the result with a timeout
        try:
            result = future.result(timeout=30)  # 30 second timeout
            print(f"[MCPClient.call_tool_sync] Got result")
            return result
        except Exception as e:
            print(f"[MCPClient.call_tool_sync] ERROR: {e}")
            raise

    async def close(self):
        print("Closing MCP client...")
        try:
            # Don't use wait_for with this - just close directly
            await self._close_internal()
        except Exception as e:
            print(f"[MCP close error ignored]: {e}")

    async def _close_internal(self):
        """Internal close method that handles cleanup properly"""
        try:
            # Give pending operations a moment to complete
            await asyncio.sleep(0.5)
            
            # Close the exit stack which will clean up session and transport
            await self.exit_stack.aclose()
        except Exception as e:
            print(f"[MCP close error in _close_internal]: {e}")
        finally:
            self.session = None
            self.stdio = None
            self.write = None
        print("MCP client closed.")