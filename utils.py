def calculate_internal_metric(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a/b
