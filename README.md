# pippin-lite
### a minimalistic template for dynamic self-building AI agents

Pippin-Lite is a lighter-weight cousin of the [Pippin](https://github.com/pippinlovesyou/pippin) framework. At 227 lines of code, it’s light-weight, approachable, and designed as an educational starting point for exploring dynamic self-building AI agents. While the core Pippin framework focuses on complex and expansive capabilities, Pippin-Lite keeps things simple and close-ended, making it perfect for exploring tasks with close-ended goals.

Unlike its robust sibling, Pippin-Lite is intentionally minimalistic. It’s focused on helping users understand the fundamentals of autonomous agents and how they build and register tools dynamically. With potential enhancements like memory and self-improvement, it offers a flexible foundation to expand your AI projects.

We’d like to thank the amazing Composio team for their help integrating Composio tools into this project!

---

Join our [Pippin Developer Hub on Discord](https://discord.gg/BJsZvZB8) to connect with other developers, share ideas, and collaborate on exciting Pippin-inspired projects.

---

## **Caution**

- **Execution Safety**: Pippin-Lite installs dependencies and executes code dynamically. Run it in a safe environment and be mindful of the tasks you define.
- **Privacy**: API keys and sensitive data should be securely managed.

---
## **Features**

- **Dynamic Tool Creation**: Automatically creates and registers tools to accomplish user-defined tasks.
- **Composio Integration**: Enables advanced workflows and seamless app integration using Composio tools.
- **Authentication Management**: Detects available API keys dynamically for various integrations.
- **Package Installation**: Automatically installs required Python packages during tool creation.
- **Error Handling**: Gracefully handles errors and iterates to complete tasks.
- **Dynamic Execution**: Iteratively builds, registers, and utilizes tools during runtime.
- **Minimalistic Design**: Designed as a lightweight introduction to autonomous agent workflows.

---

## **Getting Started**

### **Prerequisites**

- Python 3.8 or higher
- `pip` package manager

### **Installation**

1. **Clone the Repository**
   ```bash
   git clone https://github.com/pippinlovesyou/pippin-lite.git
   cd pippin-lite
   ```

2. **Create a Virtual Environment (Optional)**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set Environment Variables**
   - Create a `.env` file in the project directory and add your API keys:
     ```env
     LITELLM_MODEL=gpt-4o
     OPENAI_API_KEY=your-openai-api-key
     ```

---

## **Usage**

1. **Run the Application**
   ```bash
   python pippin-lite.py
   ```

2. **Describe the Task**
   When prompted, enter a task description. The agent will dynamically create tools and attempt to solve the task.

3. **Monitor Progress**
   Progress updates will be displayed in the console. Once the task is completed, you will see a "Task completed" message.

### **Example Tasks**
- Summarize news headlines from a website.
- Analyze an image in your folder (requires an image file).
- Search Twitter for a keyword and summarize findings.

---

## **Architecture Overview**

- **Dynamic Toolset**: Uses Composio tools for workflows and dynamic action execution.
- **LiteLLM Integration**: Manages AI interactions via [LiteLLM](https://github.com/litellm).
- **Error Recovery**: Automatically retries failed tool executions.
- **Self-Building Agent**: Dynamically creates tools to handle unforeseen tasks.

---

## **Contributing**

We encourage contributions to improve Pippin-Lite and its integration into the [Pippin framework](https://github.com/pippinlovesyou/pippin). Fork the repo, make changes, and submit a pull request. Contributions to [Pippin-Universe](https://github.com/pippinlovesyou/pippin-universe) are also welcome to share your own Pippin-inspired creations.

### **Contribution Examples**
- Enhance tool creation workflows.
- Add support for new APIs or models.
- Extend functionality for more complex tasks.

---


## **License**

Pippin-Lite is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.


Happy building with Pippin! 🦄✨
