class CLIEventHandler:
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    def __init__(self):
        self.onSuccessEvent = lambda cliNode: print("Completed")
        self.onErrorEvent = lambda cliNode: print("Completed with Errors")
        self.onCancelEvent = lambda cliNode: print("Cancelled")
        self.onFinish = lambda cliNode: None

        self.shouldProcess = True

    def getStatus(self, caller):
        return caller.GetStatusString().lower()

    def __call__(self, cliNode, event):
        if cliNode is None or not self.shouldProcess:
            return

        status = self.getStatus(cliNode)

        if status == self.COMPLETED:
            self.onSuccessEvent(cliNode)

        elif "error" in status:
            self.onErrorEvent(cliNode)

        elif status == self.CANCELLED:
            self.onCancelEvent(cliNode)

        if not cliNode.IsBusy():
            self.onFinish(cliNode)
            self.shouldProcess = False
