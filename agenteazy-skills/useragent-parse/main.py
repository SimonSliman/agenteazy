from ua_parser import user_agent_parser


def parse(ua_string):
    try:
        result = user_agent_parser.Parse(ua_string)
        return {"browser": result.get("user_agent", {}), "os": result.get("os", {}), "device": result.get("device", {})}
    except Exception as e:
        return {"error": str(e)}
