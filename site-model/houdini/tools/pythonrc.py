# Runs once at every Houdini startup: start the hrpyc RPC server (port 18811) so Claude Code's Houdini MCP can connect.
try:
    import hou, hrpyc
    if hou.isUIAvailable():
        hrpyc.start_server(port=18811)
except Exception as e:   # e.g. port already in use by another Houdini session
    print("hrpyc auto-start skipped:", e)
