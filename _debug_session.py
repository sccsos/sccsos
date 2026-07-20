"""Debug: test if AgentProcess session recording works."""

import tempfile, time
from pathlib import Path

from sccsos.core.db import Database
from sccsos.core.session import AgentSessionManager
from sccsos.core.agent_runner import AgentRunner
from sccsos.core.hermes_adapter import MockHermesAdapter

with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    path = f.name
db = Database(path)
db.initialize()
manager = AgentSessionManager(db)
adapter = MockHermesAdapter()
runner = AgentRunner(adapter, session_manager=manager)

started = runner.start_agent("test-agent")
print(f"Started: {started}")

sessions_before = manager.list_sessions(agent_name="test-agent")
print(f"Sessions before ask: {len(sessions_before)}")

t0 = time.time()
result = runner.ask_agent("test-agent", "Hello!", timeout=10)
elapsed = time.time() - t0
print(f"Ask result: success={result.success}, error={result.error}, elapsed={elapsed:.2f}s")

sessions = manager.list_sessions(agent_name="test-agent")
print(f"Sessions after ask: {len(sessions)}")

# Re-fetch session from DB
if sessions:
    sid = sessions[0].id
    msgs = manager.get_history(sid)
    print(f"Messages: {len(msgs)}")
    for m in msgs:
        print(f"  {m.role}: {m.content[:80]}")

runner.stop_all()
Path(path).unlink(missing_ok=True)
print("Done")
