"""
A simple module that provides a greeting function.

The `hello_world` function returns the standard "Hello, World!" string,
which can be used to verify that the module is working correctly
or to demonstrate a basic Python function. This module also
includes a small demo block that prints the greeting when the
script is executed directly.
"""
def hello_world():
    """
    Returns a friendly greeting string.
    
    Returns:
        str: The string "Hello, World!"
    """
    return "Hello, World!"


if __name__ == "__main__":
    # Simple demonstration when run directly
    print(hello_world())