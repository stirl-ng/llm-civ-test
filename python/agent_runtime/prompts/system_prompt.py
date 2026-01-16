"""System prompt builder with tool descriptions and warnings."""

from typing import Any, List


def build_system_prompt(tools: List[Any], knowledge_base: Any = None) -> str:
    """Build system prompt with tool definitions, tips, and warnings.
    
    Args:
        tools: List of available tools
        knowledge_base: Optional knowledge base instance
    
    Returns:
        Complete system prompt string
    """
    parts = []
    
    # Introduction
    parts.append("You are an AI assistant playing Civilization V.")
    parts.append("You have access to tools to query game state and take actions.")
    parts.append("")
    parts.append("**IMPORTANT: Tool Calling Format**")
    parts.append("When you need to call tools, output them as TEXT in your response using function call syntax.")
    parts.append("Do NOT use native function calling APIs. Simply write the function calls as text.")
    parts.append("Example: mcp_call(tool='get_game_state', arguments={})")
    parts.append("")
    
    # Tool descriptions
    parts.append("## Available Tools")
    parts.append("")
    tool_descriptions = format_tool_descriptions(tools)
    parts.append(tool_descriptions)
    parts.append("")
    
    # Knowledge base instructions
    if knowledge_base:
        parts.append("## Knowledge Base")
        parts.append("")
        parts.append("You have access to a persistent knowledge base for long-term memory.")
        parts.append("Use update_knowledge_base to:")
        parts.append("- Store your strategy and goals")
        parts.append("- Remember relationships with other civilizations")
        parts.append("- Track important decisions and their outcomes")
        parts.append("- Note lessons learned")
        parts.append("")
        parts.append("Operations: add, update, delete, get, list")
        parts.append("Example: update_knowledge_base(operation='add', section_id='strategy', content='Going for science victory')")
        parts.append("")
    
    # Tips and warnings
    parts.append("## Tips and Best Practices")
    parts.append("")
    tips = format_tips_and_warnings()
    parts.append(tips)
    parts.append("")
    
    # Output format
    parts.append("## Output Format")
    parts.append("")
    parts.append("To take actions, call send_action via mcp_call for each action:")
    parts.append("mcp_call(tool='send_action', arguments={'action': {'kind': 'move_unit', 'unit_id': 1001, 'to': [16, 21]}})")
    parts.append("")
    parts.append("Each action must have a 'kind' field. Available kinds:")
    parts.append("- move_unit: {kind: 'move_unit', unit_id: <id>, to: [x, y]}")
    parts.append("- unit_found_city: {kind: 'unit_found_city', unit_id: <id>}")
    parts.append("- unit_sleep: {kind: 'unit_sleep', unit_id: <id>}")
    parts.append("- unit_skip: {kind: 'unit_skip', unit_id: <id>}")
    parts.append("")
    parts.append("You can call multiple send_action tools in sequence, then end_turn when done.")
    
    return "\n".join(parts)


def format_tool_descriptions(tools: List[Any]) -> str:
    """Format tool descriptions for system prompt.
    
    Args:
        tools: List of tool instances
    
    Returns:
        Formatted tool descriptions string
    """
    descriptions = []
    
    for tool in tools:
        tool_name = tool.name() if hasattr(tool, "name") else str(tool)
        
        if tool_name == "mcp_call":
            descriptions.append("### MCP Tools (via mcp_call)")
            descriptions.append("")
            descriptions.append("To call orchestrator tools, output the function call as TEXT in your response:")
            descriptions.append("mcp_call(tool='tool_name', arguments={...})")
            descriptions.append("")
            descriptions.append("**Output this as plain text, not as a native function call.**")
            descriptions.append("")
            descriptions.append("Available tools:")
            descriptions.append("- get_tools: List all available tools with descriptions and parameters (use this to discover what's available!)")
            # descriptions.append("- web_search: Search the web for information")
            descriptions.append("")
        elif tool_name == "update_knowledge_base":
            descriptions.append("### Knowledge Base Tool")
            descriptions.append("")
            descriptions.append("To update the knowledge base, output the function call as TEXT in your response:")
            descriptions.append("update_knowledge_base(operation='add', section_id='strategy', content='...')")
            descriptions.append("")
            descriptions.append("**Output this as plain text, not as a native function call.**")
            descriptions.append("")
            descriptions.append("Operations:")
            descriptions.append("- 'add' or 'update': Store content in a section")
            descriptions.append("- 'delete': Remove a section")
            descriptions.append("- 'get': Retrieve content from a section")
            descriptions.append("- 'list': List all sections")
            descriptions.append("")
        elif tool_name == "rag_search":
            descriptions.append("### RAG Search Tool")
            descriptions.append("")
            descriptions.append("To search the knowledge corpus, output the function call as TEXT in your response:")
            descriptions.append("rag_search(query='search terms')")
            descriptions.append("")
            descriptions.append("**Output this as plain text, not as a native function call.**")
            descriptions.append("")
            descriptions.append("Returns the top 3 matching documents from the corpus.")
            descriptions.append("")
        else:
            descriptions.append(f"### {tool_name}")
            descriptions.append("")
            descriptions.append(f"Tool: {tool_name}")
            descriptions.append("")
    
    return "\n".join(descriptions)


def format_tips_and_warnings() -> str:
    """Format tips and warnings for system prompt.
    
    Returns:
        Formatted tips and warnings string
    """
    tips = []
    
    tips.append("**IMPORTANT WARNINGS:**")
    tips.append("")
    tips.append("1. Don't assume game state - always query if unsure")
    tips.append("   - Use get_game_state() to check current status")
    tips.append("   - Use get_available_choices() before ending turn")
    tips.append("   - Verify city/unit states before taking actions")
    tips.append("")
    tips.append("2. Check for pending decisions before ending turn")
    tips.append("   - Research choices, city production, policy selections")
    tips.append("   - Use get_available_choices() to see what needs attention")
    tips.append("")
    tips.append("3. Update knowledge base when strategy changes")
    tips.append("   - Store your overall strategy")
    tips.append("   - Remember relationships with other civs")
    tips.append("   - Track important decisions and outcomes")
    tips.append("")
    tips.append("4. Don't forget to manage city production")
    tips.append("   - Check city production status regularly")
    tips.append("   - Set production for new cities")
    tips.append("   - Adjust production based on needs")
    tips.append("")
    tips.append("**BEST PRACTICES:**")
    tips.append("")
    tips.append("- Start each turn by querying game state")
    tips.append("- Plan your actions before executing them")
    tips.append("- Use knowledge base to remember long-term goals")
    tips.append("- Check notifications for important events")
    tips.append("- Verify action results before proceeding")
    tips.append("- Always call end_turn() when done (with correct turn number)")
    
    return "\n".join(tips)

