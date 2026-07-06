"""Exceptions for resume-forge."""


class ResumeForgeError(Exception):
    """Base class for all resume-forge errors."""


class JobFetchError(ResumeForgeError):
    """Could not obtain a usable job description from the given URL."""


class LLMError(ResumeForgeError):
    """The LLM call failed or returned unusable output."""


class LatexError(ResumeForgeError):
    """LaTeX compilation failed. The message contains the relevant log excerpt."""


class IngestError(ResumeForgeError):
    """The master resume could not be read or parsed."""
