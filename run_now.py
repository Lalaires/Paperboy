from agent import run_agent
from deliver import deliver

if __name__ == "__main__":
    print("Running full pipeline...")
    briefing = run_agent()
    deliver(briefing)
    print("Done.")
