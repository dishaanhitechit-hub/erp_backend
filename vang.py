# def nth_fibonacci(n):
#     # base case
#     if n <= 1:
#         return n
#
#     # sum of the two preceding
#     # Fibonacci numbers
#     return nth_fibonacci(n - 1) + nth_fibonacci(n - 2)
#
# n= int(input())
# print(nth_fibonacci(n))

n = 1000
src = 'A'
aux = 'C'
des = 'B'

total_moves = 2 ** n - 1
if n % 2 == 0:
    des, aux = aux, des

rods = {'A': list(range(n, 0, -1)), 'B': [], 'C': []}

for move in range(1, total_moves + 1):
    if move % 3 == 1:
        from_rod, to_rod = ('A', 'B') if (rods['A'] and (not rods['B'] or rods['A'][-1] < rods['B'][-1])) else (
        'B', 'A')
    elif move % 3 == 2:
        from_rod, to_rod = ('A', 'C') if (rods['A'] and (not rods['C'] or rods['A'][-1] < rods['C'][-1])) else (
        'C', 'A')
    else:
        from_rod, to_rod = ('B', 'C') if (rods['B'] and (not rods['C'] or rods['B'][-1] < rods['C'][-1])) else (
        'C', 'B')

    disk = rods[from_rod].pop()
    rods[to_rod].append(disk)
    print(f"Move disk {disk} from {from_rod} to {to_rod}")