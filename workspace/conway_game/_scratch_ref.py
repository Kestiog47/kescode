def tick(alive, w=8, h=8):
    nxt = set()
    for x in range(w):
        for y in range(h):
            n = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    if (dx, dy) != (0, 0) and (x + dx, y + dy) in alive)
            if (x, y) in alive and n in (2, 3):
                nxt.add((x, y))
            elif (x, y) not in alive and n == 3:
                nxt.add((x, y))
    return nxt


# blinker horizontal at (1,2),(2,2),(3,2) in 5x5
b = {(1, 2), (2, 2), (3, 2)}
print('blinker gen1:', sorted(tick(b, 5, 5)))
print('blinker gen2:', sorted(tick(tick(b, 5, 5), 5, 5)))

# glider in 6x6
g = {(1, 0), (2, 1), (0, 2), (1, 2), (2, 2)}
g1 = tick(g, 6, 6)
print('glider gen1:', sorted(g1))
print('glider gen2:', sorted(tick(g1, 6, 6)))

# L-shape corner reproduction in 3x3
l = {(0, 0), (0, 1), (1, 0)}
print('L gen1:', sorted(tick(l, 3, 3)))

# overpopulation plus-shape centre (2,2) in 5x5
p = {(2, 2), (1, 2), (3, 2), (2, 1), (2, 3)}
print('plus gen1:', sorted(tick(p, 5, 5)))

# 3x3 full block: centre dies (8 neighbours), corners survive (3 neighbours)
full = {(x, y) for x in (1, 2, 3) for y in (1, 2, 3)}
print('3x3full gen1:', sorted(tick(full, 5, 5)))
