"""Quick smoke test for the strategy agent.

Run with:
    python test_engine.py
"""

from agents.graph import app


def run_tests():
    print("🚀 Starting strategy engine tests...\n")

    prospects = [
        {
            "prospect_name": "Thomas (Tech Lead)",
            "has_email": True,
            "has_phone": False,
            "recent_posts_context": (
                "Posts 3 times a week about AI and Python. Uses lots of emojis 🚀🔥. "
                "Very casual and technical tone."
            ),
        },
        {
            "prospect_name": "Ms Dubois (Director, 5-star Palace Hotel)",
            "has_email": True,
            "has_phone": True,
            "recent_posts_context": (
                "No posts in 2 years. Very institutional profile, formal tone, "
                "formal address expected."
            ),
        },
    ]

    for prospect in prospects:
        print("=" * 50)
        print(f"🧠 ANALYSING: {prospect['prospect_name']}")
        print("=" * 50)

        result = app.invoke(prospect)
        plan = result.get("final_plan")

        if plan:
            for step in plan.sequence:
                print(f"📍 Step {step.step} | Timing: {step.timing} | Channel: {step.channel}")
                print(f"   Action: {step.recommended_action}")
                print(f"   💡 Why: {step.justification}\n")
        else:
            print("❌ No plan returned.\n")


if __name__ == "__main__":
    run_tests()
