"""ACP foundation exception types."""


class AcpError(Exception):
    """Base class for ACP foundation failures."""


class AcpTransportError(AcpError):
    """Raised when the stdio transport cannot operate correctly."""


class AcpProcessExitedError(AcpTransportError):
    """Raised when the child process exits unexpectedly."""


class AcpJsonRpcError(AcpError):
    """Raised when a JSON-RPC peer returns a structured error."""

    def __init__(self, code: int | None, message: str, data=None):
        self.code = code
        self.data = data
        super().__init__(message)


class AcpTimeoutError(AcpError):
    """Raised when an ACP operation times out."""


class AcpProtocolError(AcpError):
    """Raised when protocol data is malformed or invalid."""
