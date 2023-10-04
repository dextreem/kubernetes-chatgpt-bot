# Base needed imports

# Internal resources

# External resources
import os

class ResponseCheckRetryError(Exception):
    def __init__(self, message="", maxRetryCounter: int = -1):
        if message != "":
            self.message = f"{message}{os.linesep}"
        self.message += f"The maximum number of retries ({str(maxRetryCounter)}) was reached!"
        super().__init__(self.message)
