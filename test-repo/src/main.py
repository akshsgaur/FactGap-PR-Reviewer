"""Main application module"""

from typing import List


def calculate_sum(numbers: List[int]) -> int:
    """Calculate the sum of a list of numbers.
    
    Args:
        numbers: List of integers to sum
        
    Returns:
        The sum of all numbers
    """
    total = 0
    for num in numbers:
        total += num
    return total


def calculate_average(numbers: List[int]) -> float:
    """Calculate the average of a list of numbers.
    
    Args:
        numbers: List of integers
        
    Returns:
        The average value
    """
    if not numbers:
        return 0.0
    
    return calculate_sum(numbers) / len(numbers)


if __name__ == "__main__":
    sample_numbers = [1, 2, 3, 4, 5]
    print(f"Sum: {calculate_sum(sample_numbers)}")
    print(f"Average: {calculate_average(sample_numbers)}")
