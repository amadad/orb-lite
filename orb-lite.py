import os, json, traceback, subprocess, sys
from time import sleep, time
from langchain_core.tools import tool
from litellm import completion
from dotenv import load_dotenv
from composio_openai import ComposioToolSet, App, Action

load_dotenv()

toolset = ComposioToolSet()

# ANSI escape codes for color and formatting
class Colors:
    HEADER = '\033[95m'; OKBLUE = '\033[94m'; OKCYAN = '\033[96m'; OKGREEN = '\033[92m'
    WARNING = '\033[93m'; FAIL = '\033[91m'; ENDC = '\033[0m'; BOLD = '\033[1m'; UNDERLINE = '\033[4m'

# Configuration
MODEL_NAME = os.environ.get('LITELLM_MODEL', 'gpt-4o')
tools, available_functions = [], {}
MAX_TOOL_OUTPUT_LENGTH = 5000  # Adjust as needed
MAX_ITERATIONS_BEFORE_BREAK = 10 # Break loop after this many iterations without tool calls

# Automatically detect available API keys
api_key_patterns = ['API_KEY', 'ACCESS_TOKEN', 'SECRET_KEY', 'TOKEN', 'APISECRET']
available_api_keys = [key for key in os.environ.keys() if any(pattern in key.upper() for pattern in api_key_patterns)]

def register_tool(name, func, description, parameters):
    global tools
    tools = [tool for tool in tools if tool["function"]["name"] != name]
    available_functions[name] = func
    tools.append({
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": parameters,
                "required": list(parameters.keys())
            }
        }
    })
    print(f"{Colors.OKGREEN}{Colors.BOLD}Registered tool:{Colors.ENDC} {name}")

def create_or_update_tool(name, code, description, parameters):
    try:
        exec(code, globals())
        register_tool(name, globals()[name], description, parameters)
        return f"Tool '{name}' created/updated successfully."
    except Exception as e:
        return f"Error creating/updating tool '{name}': {e}"

def install_package(package_name):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        return f"Package '{package_name}' installed successfully."
    except Exception as e:
        return f"Error installing package '{package_name}': {e}"

def serialize_tool_result(tool_result, max_length=MAX_TOOL_OUTPUT_LENGTH):
    try:
        serialized_result = json.dumps(tool_result)
    except TypeError:
        serialized_result = str(tool_result)
    if len(serialized_result) > max_length:
        return serialized_result[:max_length] + f"\n\n{Colors.WARNING}(Note: Result was truncated to {max_length} characters out of {len(serialized_result)} total characters.){Colors.ENDC}"
    else:
        return serialized_result

def call_tool(function_name, args):
    func = available_functions.get(function_name)
    if not func:
        print(f"{Colors.FAIL}{Colors.BOLD}Error:{Colors.ENDC} Tool '{function_name}' not found.")
        return f"Tool '{function_name}' not found."
    try:
        print(f"{Colors.OKBLUE}{Colors.BOLD}Calling tool:{Colors.ENDC} {function_name} with args: {args}")
        result = func(**args)
        print(f"{Colors.OKCYAN}{Colors.BOLD}Result of {function_name}:{Colors.ENDC} {result}")
        return result
    except Exception as e:
        print(f"{Colors.FAIL}{Colors.BOLD}Error:{Colors.ENDC} Error executing '{function_name}': {e}")
        return f"Error executing '{function_name}': {e}"

def task_completed():
    return "Task marked as completed."

# Initialize basic tools
register_tool("create_or_update_tool", create_or_update_tool, "Creates or updates a tool with the specified name, code, description, and parameters.", {
    "name": {"type": "string", "description": "The tool name."},
    "code": {"type": "string", "description": "The Python code for the tool."},
    "description": {"type": "string", "description": "A description of the tool."},
    "parameters": {
        "type": "object",
        "description": "A dictionary defining the parameters for the tool.",
        "additionalProperties": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "Data type of the parameter."},
                "description": {"type": "string", "description": "Description of the parameter."}
            },
            "required": ["type", "description"]
        }
    }
})


# Register Composio tools
composio_tools = toolset.get_tools(apps=[App.COMPOSIO])
for tool in composio_tools:
    tools.append(tool)
    name = tool['function']['name']
    available_functions[name] = lambda tool_name=name, **kwargs: toolset.execute_action(
        action=tool_name,
        params=kwargs
    )


register_tool("install_package", install_package, "Installs a Python package using pip.", {
    "package_name": {"type": "string", "description": "The name of the package to install."}
})


register_tool("task_completed", task_completed, "Marks the current task as completed.", {})

# Main loop to handle user input and LLM interaction
def run_main_loop(user_input):
    # Include available API keys in the system prompt
    if available_api_keys:
        api_keys_info = "Available API keys:\n" + "\n".join(f"- {key}" for key in available_api_keys) + "\n\n"
    else:
        api_keys_info = "No API keys are available.\n\n"

    messages = [{
        "role": "system",
        "content": (
"""
You are an AI assistant designed to help users interact with Composio's tools and workflows. Your primary approach will be to use the composio_workflow function, with fallback capabilities to build custom tools when needed.
PRIMARY WORKFLOW:
1. When given a task, first attempt to use the Composio tools with these steps:
   - Search for available tools using the usecase parameter
   - Select appropriate tool_name based on the task requirements
   - List and select relevant actions for the chosen tool
   - Execute actions with proper parameters.
   - Handle authentication flows when required
   - When retrieving apps, pass only the usecase parameter
   - When using Composio Execute Action to execute a tool specific action , you need to pass the params for example '{action_name: "GOOGLEDOCS_CREATE_DOCUMENT", request: {title: "doc", text: "Initial text for the document."}}'
   - After initiating a connection, you need to use the Composio Wait For Connection action for 15 seconds to wait for the connection to be established.
   - After waiting for connection, you need to use the Composio Check Active Connection action to check if the connection is active.
   - After checking if the connection is active, you need to use the Composio Execute Action action to execute the action.
The composio_workflow function accepts:
- usecase (str): Required - The use case to search for tools and actions
- tool_name (str): Optional - Specific tool to use
- action_name (str): Optional - Specific action to execute
- action_params (dict): Required if action_name is provided
FALLBACK WORKFLOW:
If the composio_workflow function cannot accomplish the task, fall back to the custom tool creation approach:
1. **create_or_update_tool**: Create new functions or update existing ones by providing:
   - function name
   - code
   - description
   - parameters (JSON schema format)
   Example parameters:
   ```json
   {
     "param1": {"type": "string", "description": "Description of param1"},
     "param2": {"type": "integer", "description": "Description of param2"}
   }
   ```
2. **install_package**: Install Python packages as needed
3. **task_completed**: Signal task completion
Available Resources:
- Composio platform access (Gmail, Google Sheets, Docs, Calendar, etc.)
- API keys: {api_keys_info}
Best Practices:
- Always attempt the composio_workflow function first
- Handle authentication flows when prompted
- Be token-efficient in responses
- Provide complete code when creating tools
- Handle errors gracefully
- Use available API keys when possible
- Only prompt for user input when absolutely necessary
- When online information is needed, create appropriate tools to fetch it
Error Handling:
- If composio_workflow fails, analyze the error
- Switch to fallback workflow if needed
- Adjust tool parameters or create new tools as required
- Document any unsuccessful attempts for future reference
Complete the task by:
1. Trying composio_workflow first
2. Falling back to custom tools if needed
3. Using task_completed() when finished
Remember to provide all required parameters for function calls and maintain awareness of token limits when handling tool outputs.
"""
        )
    }, {"role": "user", "content": user_input}]
    iteration, max_iterations = 0, 50
    iterations_without_tool_call = 0 # Initialize counter for iterations without tool calls
    last_agent_message_content = None # Store the last content message from the agent
    while iteration < max_iterations:
        print(f"{Colors.HEADER}{Colors.BOLD}Iteration {iteration + 1} running...{Colors.ENDC}")
        try:
            response = completion(model=MODEL_NAME, messages=messages, tools=tools, tool_choice="auto")
            response_message = response.choices[0].message
            if response_message.content:
                print(f"{Colors.OKCYAN}{Colors.BOLD}LLM Response:{Colors.ENDC}\n{response_message.content}\n")
                last_agent_message_content = response_message.content # Store the content
            messages.append(response_message)
            if response_message.tool_calls:
                iterations_without_tool_call = 0 # Reset counter because a tool was called
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    tool_result = call_tool(function_name, args)
                    serialized_tool_result = serialize_tool_result(tool_result)
                    messages.append({
                        "role": "tool",
                        "name": function_name,
                        "tool_call_id": tool_call.id,
                        "content": serialized_tool_result
                    })
                if 'task_completed' in [tc.function.name for tc in response_message.tool_calls]:
                    print(f"{Colors.OKGREEN}{Colors.BOLD}Task completed.{Colors.ENDC}")
                    break
            else:
                iterations_without_tool_call += 1 # Increment counter if no tool call
                if iterations_without_tool_call >= MAX_ITERATIONS_BEFORE_BREAK: # Check if limit reached
                    print(f"{Colors.WARNING}{Colors.BOLD}Possible loop detected. Agent message:{Colors.ENDC}\n\"{last_agent_message_content}\"\n") # Print last agent message
                    user_break_input = input(f"""{Colors.WARNING}{Colors.BOLD}Choose action:{Colors.ENDC}
                    1: Continue iteration
                    2: Redirect agent with new instructions
                    3: Stop task
                    Enter choice (1, 2, or 3): """)
                    if user_break_input == '2':
                        new_instruction = input("Enter new instructions for the agent: ")
                        messages.append({"role": "user", "content": new_instruction}) # Add new user message
                        iterations_without_tool_call = 0 # Reset counter
                    elif user_break_input == '3':
                        print(f"{Colors.WARNING}{Colors.BOLD}Breaking loop and stopping task based on user input.{Colors.ENDC}")
                        break
                    else: # Default to continue (or if user enters '1')
                        iterations_without_tool_call = 0 # Reset counter if user wants to continue
        except Exception as e:
            print(f"{Colors.FAIL}{Colors.BOLD}Error:{Colors.ENDC} Error in main loop: {e}")
            traceback.print_exc()
        iteration += 1
        sleep(2)
    print(f"{Colors.WARNING}{Colors.BOLD}Max iterations reached or task completed.{Colors.ENDC}")

if __name__ == "__main__":
    run_main_loop(input(f"{Colors.BOLD}Describe the task you want to complete: {Colors.ENDC}"))
