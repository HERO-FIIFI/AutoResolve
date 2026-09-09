# Decision engine

Input: untrusted redacted ticket and retrieved evidence. Output: Pydantic-validated `Decision` JSON.
Malformed, incomplete, or contract-breaking responses are provider failures. Model text never
directly causes a customer response.

