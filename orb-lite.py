#!/usr/bin/env python3

import os
import json
import traceback
import subprocess
import sys
import time
from time import sleep
from functools import wraps
import warnings

# Suppress pydantic warning about removed config keys
warnings.filterwarnings("ignore", message="Valid config keys have changed in V2")

# Suppress Composio warnings
warnings.filterwarnings("ignore", category=UserWarning, module="composio.*")

from dotenv import load_dotenv
from composio_openai import ComposioToolSet, App, Action
from langchain_core.tools import tool
from litellm import completion

# ------------------------------------------------------------------------------
# Environment Setup
# ------------------------------------------------------------------------------

load_dotenv()
MODEL_NAME = os.environ.get('LITELLM_MODEL', 'gpt-4o')

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Initialize Composio toolset
toolset = ComposioToolSet()

# Global data
tools = []
available_functions = {}
connection_cache = {}
CONNECTIONS_FILE = ".composio.connections"
MAX_TOOL_OUTPUT_LENGTH = 5000
MAX_ITERATIONS_BEFORE_BREAK = 10

# Automatically detect environment variables that look like API keys
api_key_patterns = ['API_KEY', 'ACCESS_TOKEN', 'SECRET_KEY', 'TOKEN', 'APISECRET']
available_api_keys = [
    key for key in os.environ.keys()
    if any(pattern in key.upper() for pattern in api_key_patterns)
]
api_keys_info = "\n".join(
    [f"- {key}: {os.environ.get(key)}" for key in available_api_keys]
) if available_api_keys else "No API keys detected. Ensure they are set as environment variables."

# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------

def register_tool(name, func, description, parameters):
    """
    Registers a tool dynamically by adding it to the toolset.
    """
    global tools
    # Remove any existing definition for this tool
    tools = [t for t in tools if t["function"]["name"] != name]
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
    """
    Dynamically creates or updates a tool using Python code.
    """
    try:
        exec(code, globals())
        register_tool(name, globals()[name], description, parameters)
        return f"Tool '{name}' created/updated successfully."
    except Exception as e:
        return f"Error creating/updating tool '{name}': {e}"

def install_package(package_name):
    """
    Installs a Python package dynamically using pip.
    """
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        return f"Package '{package_name}' installed successfully."
    except Exception as e:
        return f"Error installing package '{package_name}': {e}"

def task_completed():
    """
    Marks the task as completed.
    """
    return "Task marked as completed."

def serialize_tool_result(tool_result, max_length=MAX_TOOL_OUTPUT_LENGTH):
    """
    Serializes tool output into a JSON-friendly string, truncating if necessary.
    """
    try:
        serialized_result = json.dumps(tool_result)
    except TypeError:
        serialized_result = str(tool_result)
    if len(serialized_result) > max_length:
        return (
            serialized_result[:max_length] +
            f"\n\n{Colors.WARNING}(Note: Result was truncated to {max_length} characters out of {len(serialized_result)} total characters.){Colors.ENDC}"
        )
    else:
        return serialized_result

def check_existing_connection(app_name):
    """Check if we already have an active connection for a specific app."""
    try:
        entity = toolset.get_entity(id="default")
        connection = entity.get_connection(app=app_name)
        return connection and getattr(connection, 'status', 'ACTIVE') == 'ACTIVE'
    except:
        return False

def retry_on_timeout(max_retries=3, delay=2):
    """
    Decorator to retry functions on timeout or server errors.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    result = func(*args, **kwargs)
                    # Check for error/timeouts in the result
                    print(f"Retry Decorator Result: {result}") # Debug print in decorator
                    if isinstance(result, dict):
                        error_msg = result.get("error", "") # Get error safely
                        if error_msg and isinstance(error_msg, str) and ("timeout" in error_msg.lower() or "524" in error_msg): # Safe .lower() call
                            raise TimeoutError(error_msg)
                    return result
                except Exception as e:
                    retries += 1
                    if retries == max_retries:
                        print(f"{Colors.FAIL}Failed after {max_retries} retries: {str(e)}{Colors.ENDC}")
                        return {"successfull": False, "error": f"Failed after {max_retries} retries: {str(e)}"}
                    print(f"{Colors.WARNING}Retry {retries}/{max_retries} after error: {str(e)}{Colors.ENDC}")
                    time.sleep(delay)
            return result
        return wrapper
    return decorator

@retry_on_timeout()
def execute_composio_action(action_name, params):
    """Execute Composio action with retry logic."""
    try:
        print(f"Executing Composio action: {action_name} with params: {params}")

        result = toolset.execute_action(
            action=action_name,
            params=params
        )

        print(f"Composio action result: {result}") # Debug print in action function

        # If we get None result, it actually succeeded for Composio actions
        if result is None:
            return {"successfull": True}

        # Handle explicit errors in result dict
        if isinstance(result, dict) and result.get("error"):
            if "No metadata found for enum" in str(result.get("error")):
                print(f"{Colors.WARNING}Invalid action name: {action_name}{Colors.ENDC}")
            else:
                print(f"{Colors.WARNING}Action error: {result['error']}{Colors.ENDC}")
            # Do not raise exception here, let retry handle it
            return result # Return error dict for retry logic to handle
        elif result is None: # Treat explicit None as error after debug print
            return {"successfull": False, "error": "Composio action returned None unexpectedly."} # Return error dict

        return result

    except Exception as e:
        print(f"{Colors.FAIL}Action execution error: {str(e)}{Colors.ENDC}")
        return {"error": str(e)}

def call_tool(function_name, args):
    """Calls a registered tool and handles errors gracefully."""
    func = available_functions.get(function_name)
    if not func:
        print(f"{Colors.FAIL}{Colors.BOLD}Error:{Colors.ENDC} Tool '{function_name}' not found.")
        return f"Tool '{function_name}' not found."

    try:
        # Check if this is an initiate connection call and we already have a connection
        if function_name == "COMPOSIO_INITIATE_CONNECTION":
            app_name = args.get("tool")
            if app_name and check_existing_connection(app_name):
                print(f"{Colors.OKGREEN}Using existing connection for {app_name}{Colors.ENDC}")
                return {"successfull": True, "data": {"active_connection": True}}

        print(f"{Colors.OKBLUE}{Colors.BOLD}Calling tool:{Colors.ENDC} {function_name} with args: {args}")
        
        # Handle COMPOSIO_EXECUTE_ACTION
        if function_name == "COMPOSIO_EXECUTE_ACTION":
            # Convert action_name to action if needed
            action = args.get("action") or args.get("action_name")
            if not action:
                return {"error": "Missing 'action' field in COMPOSIO_EXECUTE_ACTION"}
            
            params = args.get("params", {})
            return execute_composio_action(action, params)
        
        # Execute other functions normally
        result = func(**args)
        
        # Handle authorization responses
        if isinstance(result, dict):
            if result.get("data") and result["data"].get("response_data", {}).get("redirect_url"):
                auth_url = result["data"]["response_data"]["redirect_url"]
                instruction = result["data"].get("instruction", "Please complete authorization")
                print(f"{Colors.WARNING}{Colors.BOLD}Authorization Required:{Colors.ENDC}")
                print(f"{Colors.WARNING}URL: {auth_url}{Colors.ENDC}")

                user_choice = input(f"""{Colors.WARNING}{Colors.BOLD}Choose action:{Colors.ENDC}
1: Complete authorization ({auth_url})
2: Skip tool ({function_name}) authorization
3: Redirect agent with new instructions
4: Stop task
Enter choice (1-4): """)

                if user_choice == "1":
                    print(f"{Colors.WARNING}Please complete authorization at the URL provided.{Colors.ENDC}")
                    input("Press Enter after completing authorization...")
                    return {"authorization_completed": True, "tool": function_name}
                elif user_choice == "2":
                    return {"skip_tool": True, "tool": function_name}
                elif user_choice == "3":
                    new_instructions = input("Enter new instructions: ")
                    return {"redirect": True, "new_instructions": new_instructions}
                elif user_choice == "4":
                    return {"stop_task": True}
                else:
                    print(f"{Colors.WARNING}Invalid choice. Defaulting to skip tool.{Colors.ENDC}")
                    return {"skip_tool": True, "tool": function_name}

            # If we see an explicit unauthorized error
            elif "unauthorized" in str(result.get("error", "")).lower():
                print(f"{Colors.WARNING}{Colors.BOLD}Authorization Required:{Colors.ENDC} {result['error']}")
                return {"authorization_required": True, "error": result["error"]}

        return result

    except Exception as e:
        error_message = str(e)
        print(f"{Colors.FAIL}{Colors.BOLD}Error:{Colors.ENDC} Error executing '{function_name}': {e}")
        return f"Error executing '{function_name}': {e}"

# ------------------------------------------------------------------------------
# Register Basic Tools
# ------------------------------------------------------------------------------

register_tool(
    "create_or_update_tool",
    create_or_update_tool,
    "Creates or updates a Python tool.",
    {
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
    }
)

register_tool(
    "install_package",
    install_package,
    "Installs a Python package using pip.",
    {
        "package_name": {"type": "string", "description": "The name of the package to install."}
    }
)

register_tool(
    "task_completed",
    task_completed,
    "Marks the task as completed.",
    {}
)

# Incorporate only specific Composio actions we need
def register_composio_actions():
    """Register Composio tools directly."""
    composio_tools = toolset.get_tools(apps=[App.COMPOSIO])
    for tool in composio_tools:
        tools.append(tool)
        name = tool['function']['name']
        available_functions[name] = lambda tool_name=name, **kwargs: toolset.execute_action(
            action=tool_name,
            params=kwargs
        )

# Replace the existing Composio tools registration with our new function
register_composio_actions()

# ------------------------------------------------------------------------------
# Main Loop
# ------------------------------------------------------------------------------

def run_main_loop(user_input):
    messages = [
        {
            "role": "system",
            "content": """
You are an AI agent that can dynamically create and use tools to perform tasks.
You have access to a set of tools, including:
- create_or_update_tool: Creates or updates a Python tool
- install_package: Installs a Python package
- task_completed: Marks the task as completed

For Composio integrations:
1. First check if app is connected:
   COMPOSIO_INITIATE_CONNECTION(tool="twitter")

2. If authorization needed, guide user through the process

3. Execute actions with proper parameters:
   COMPOSIO_EXECUTE_ACTION(action="TWITTER_RECENT_SEARCH", params={"query": "your search term", "max_results": 10})

Error Handling:
- Always check response for authorization_required
- Handle errors gracefully with retries
- Provide clear feedback to users

Available Resources:
- Composio platform access (Twitter, Gmail, etc)
- API keys: """ + api_keys_info + """

Best Practices:
- Use proper parameter names (action, params)
- Handle authorization flows properly
- Provide clear error messages
- Document any unsuccessful attempts

Complete tasks by:
1. Checking for existing connections
2. Using proper parameter format
3. Handling errors gracefully
4. Using task_completed() when finished

Example for Google Docs:
COMPOSIO_EXECUTE_ACTION(
    action="GOOGLEDOCS_CREATE_DOCUMENT",  # This is the correct action name
    params={
        "title": "Your Title",
        "text": "Your Content"  # Note: it's 'text', not 'content'
    }
)
"""
        },
        {"role": "user", "content": user_input}
    ]

    iteration, max_iterations = 0, 50
    iterations_without_tool_call = 0
    last_agent_message_content = None
    last_tool_result = None

    while iteration < max_iterations:
        print(f"{Colors.HEADER}{Colors.BOLD}Iteration {iteration + 1} running...{Colors.ENDC}")
        try:
            response = completion(model=MODEL_NAME, messages=messages, tools=tools, tool_choice="auto")
            response_message = response.choices[0].message

            # Print the LLM content if any
            if response_message.content:
                print(f"{Colors.OKCYAN}{Colors.BOLD}LLM Response:{Colors.ENDC}\n{response_message.content}\n")
                last_agent_message_content = response_message.content

            # Add LLM response to conversation
            messages.append(response_message)

            if response_message.tool_calls:
                # Reset the no-tool-call counter
                iterations_without_tool_call = 0
                authorization_needed = False
                tool_call_failed = False

                # Process each tool call in the response
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    tool_result = call_tool(function_name, args)
                    last_tool_result = tool_result

                    # Handle special dict return signals
                    if isinstance(tool_result, dict):
                        if tool_result.get("authorization_completed"):
                            messages.append({
                                "role": "tool",
                                "name": function_name,
                                "tool_call_id": tool_call.id,
                                "content": serialize_tool_result(tool_result)
                            })
                            messages.append({
                                "role": "user",
                                "content": f"Authorization completed for {tool_result['tool']}. Please proceed with the task."
                            })
                            break
                        elif tool_result.get("skip_tool"):
                            messages.append({
                                "role": "tool",
                                "name": function_name,
                                "tool_call_id": tool_call.id,
                                "content": serialize_tool_result(tool_result)
                            })
                            messages.append({
                                "role": "user",
                                "content": f"Please try an alternative approach without using {tool_result['tool']}."
                            })
                            break
                        elif tool_result.get("redirect"):
                            messages.append({
                                "role": "tool",
                                "name": function_name,
                                "tool_call_id": tool_call.id,
                                "content": serialize_tool_result(tool_result)
                            })
                            messages.append({
                                "role": "user",
                                "content": tool_result["new_instructions"]
                            })
                            break
                        elif tool_result.get("stop_task"):
                            messages.append({
                                "role": "tool",
                                "name": function_name,
                                "tool_call_id": tool_call.id,
                                "content": serialize_tool_result(tool_result)
                            })
                            print(f"{Colors.WARNING}{Colors.BOLD}Task stopped by user.{Colors.ENDC}")
                            return
                        elif tool_result.get("authorization_required"):
                            # Add tool response for authorization required
                            messages.append({
                                "role": "tool",
                                "name": function_name,
                                "tool_call_id": tool_call.id,
                                "content": serialize_tool_result(tool_result)
                            })
                            print(f"{Colors.WARNING}{Colors.BOLD}Authorization required. Please try again.{Colors.ENDC}")
                            authorization_needed = True
                            break

                    # For normal returns, record the result as a tool message
                    serialized_tool_result = serialize_tool_result(tool_result)
                    messages.append({
                        "role": "tool",
                        "name": function_name,
                        "tool_call_id": tool_call.id,
                        "content": serialized_tool_result
                    })

                    # Specifically handle connection initiation
                    if function_name == "COMPOSIO_INITIATE_CONNECTION" and isinstance(tool_result, dict):
                        if tool_result.get("data") and tool_result["data"].get("instruction"):
                            # We have an authorization flow
                            print(f"{Colors.WARNING}{Colors.BOLD}Authorization Required: {tool_result['data']['instruction']}{Colors.ENDC}")
                            print(f"{Colors.WARNING}{Colors.BOLD}Authorization URL: {tool_result['data']['response_data']['redirect_url']}{Colors.ENDC}")

                            user_break_input = input(f"""{Colors.WARNING}{Colors.BOLD}Authorization Required for Composio Tool:{Colors.ENDC}
Instruction: {tool_result['data']['instruction']}
Authorization URL: {tool_result['data']['response_data']['redirect_url']}
Choose action:
1: Skip this tool and try alternative approach
2: Redirect agent with new instructions
3: Stop task
4: Complete authorization and continue
Enter choice (1-4): """)

                            if user_break_input == '1':
                                messages.append({
                                    "role": "user",
                                    "content": "The previous tool requires authorization. Please try an alternative approach."
                                })
                                break
                            elif user_break_input == '2':
                                new_instruction = input("Enter new instructions for the agent: ")
                                messages.append({"role": "user", "content": new_instruction})
                                break
                            elif user_break_input == '3':
                                print(f"{Colors.WARNING}{Colors.BOLD}Stopping task based on user input.{Colors.ENDC}")
                                return
                            elif user_break_input == '4':
                                print(f"{Colors.WARNING}{Colors.BOLD}Waiting for authorization to complete...{Colors.ENDC}")
                                input("Press Enter after you have completed the authorization process...")
                                messages.append({
                                    "role": "user",
                                    "content": "Authorization completed. Please proceed with checking connection and executing the action."
                                })
                                break
                            else:
                                print(f"{Colors.WARNING}{Colors.BOLD}Invalid choice. Defaulting to skip tool.{Colors.ENDC}")
                                messages.append({
                                    "role": "user",
                                    "content": "The previous tool requires authorization. Please try an alternative approach."
                                })
                                break
                        elif tool_result.get("error"):
                            print(f"{Colors.WARNING}{Colors.BOLD}Connection Error: {tool_result['error']}{Colors.ENDC}")
                            messages.append({
                                "role": "user",
                                "content": f"Connection failed: {tool_result['error']}. Try again or suggest an alternative."
                            })
                            break

                if tool_call_failed:
                    iterations_without_tool_call += 1

                if authorization_needed:
                    # Immediately break if we hit an authorization requirement
                    break

                # If 'task_completed' was in the calls, we're done
                if 'task_completed' in [tc.function.name for tc in response_message.tool_calls]:
                    print(f"{Colors.OKGREEN}{Colors.BOLD}Task completed.{Colors.ENDC}")

                    # --- Post-task completion prompt ---
                    user_choice_after_completion = input(f"""{Colors.OKGREEN}{Colors.BOLD}Task Completed. Choose action:{Colors.ENDC}
1: Continue with a new request
2: Exit
Enter choice (1-2): """)

                    if user_choice_after_completion == "1":
                        new_user_task = input(f"{Colors.BOLD}Describe your next task: {Colors.ENDC}")
                        run_main_loop(new_user_task) # Recursive call for new task
                        return  # Exit current loop after starting new task
                    elif user_choice_after_completion == "2":
                        print(f"{Colors.WARNING}{Colors.BOLD}Exiting.{Colors.ENDC}")
                        return  # Exit script
                    else:
                        print(f"{Colors.WARNING}Invalid choice. Exiting.{Colors.ENDC}")
                        return  # Exit script if invalid choice
                    # --- End post-task completion prompt ---
                    break # Break out of the main loop after handling completion

            else:
                # No tool calls in the LLM response => check for loop
                iterations_without_tool_call += 1
                if iterations_without_tool_call >= MAX_ITERATIONS_BEFORE_BREAK:
                    print(f"{Colors.WARNING}{Colors.BOLD}Possible loop detected. Agent last message:{Colors.ENDC}\n\"{last_agent_message_content}\"\n")
                    # Decide user action
                    if (isinstance(last_tool_result, dict) and last_tool_result.get("authorization_required")):
                        user_break_input = input(f"""{Colors.WARNING}{Colors.BOLD}Authorization Required for Composio Tool:{Colors.ENDC}
Last tool error: {last_tool_result.get("error")}
Choose action:
1: Continue iteration
2: Redirect agent with new instructions
3: Stop task
Enter choice (1-3): """)
                    else:
                        user_break_input = input(f"""{Colors.WARNING}{Colors.BOLD}Choose action:{Colors.ENDC}
1: Continue iteration
2: Redirect agent with new instructions
3: Stop task
Enter choice (1-3): """)

                    if user_break_input == '2':
                        new_instruction = input("Enter new instructions for the agent: ")
                        messages.append({"role": "user", "content": new_instruction})
                        iterations_without_tool_call = 0
                    elif user_break_input == '3':
                        print(f"{Colors.WARNING}{Colors.BOLD}Stopping task based on user input.{Colors.ENDC}")
                        break
                    else:
                        iterations_without_tool_call = 0

        except Exception as e:
            print(f"{Colors.FAIL}{Colors.BOLD}Error:{Colors.ENDC} Error in main loop: {e}")
            traceback.print_exc()

        iteration += 1
        sleep(2)

    print(f"{Colors.WARNING}{Colors.BOLD}Max iterations reached or task completed.{Colors.ENDC}")

# ------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    user_task = input(f"{Colors.BOLD}Describe the task you want to complete: {Colors.ENDC}")
    run_main_loop(user_task)