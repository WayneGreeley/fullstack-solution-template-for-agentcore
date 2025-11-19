"""Code interpreter tools for agent."""

import json
import logging
import boto3
from strands import tool

logger = logging.getLogger(__name__)


class CodeInterpreterTools:
    """Tools for code execution via AgentCore Code Interpreter."""

    def __init__(self, session: boto3.Session, region: str):
        """
        Initialize the code interpreter tools.

        Args:
            session: Boto3 session for AWS operations
            region: AWS region for code interpreter
        """
        self.session = session
        self.region = region
        self._code_client = None

    def _get_code_interpreter_client(self):
        """Get or create code interpreter client."""
        if self._code_client is None:
            from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter
            
            self._code_client = CodeInterpreter(self.region)
            self._code_client.start()
            logger.info(f"Started code interpreter in {self.region}")
        return self._code_client

    def cleanup(self):
        """Clean up code interpreter session."""
        if self._code_client:
            self._code_client.stop()
            self._code_client = None

    @tool
    def execute_python(self, code: str, description: str = "") -> str:
        """
        Execute Python code in secure sandbox.

        Args:
            code: Python code to execute
            description: Optional description

        Returns:
            JSON string with execution result
        """
        if description:
            code = f"# {description}\n{code}"

        client = self._get_code_interpreter_client()
        response = client.invoke("executeCode", {
            "code": code,
            "language": "python",
            "clearContext": False
        })

        for event in response["stream"]:
            return json.dumps(event["result"], indent=2)
