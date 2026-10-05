---
layout: post
title: "Variables, Values and References: How a Name Finds Its Data"
description: "A beginner-friendly explanation of variables, values and references, and why copying a list behaves differently from copying a number across languages."
date: 2026-10-05 06:00:00 +0000
categories: software-engineering beginner
tags: coding software-engineer scratch memory python javascript csharp rust
author: manishtiwari25
image:
  path: /assets/img/headers/beginner/variables_values_references.webp
  alt: Beginner header diagram comparing value copies, where two variables each hold the number 42, with reference copies, where two variables hold the same address pointing at one list in memory
---

## TL;DR

A variable is a **name** for a place that holds data. Some variables hold the data itself (a *value*); others hold the *address* where the data lives (a *reference*). Copying a value duplicates the data. Copying a reference duplicates only the address, so two names end up looking at the same thing. Almost every "why did my other variable change?!" bug in a beginner's first year comes from this single idea.

This is the third article in the beginner series. If you missed the earlier ones, start with [How to Become a Software Engineer](/posts/Software_Engineer-Beginner/) and [The Language of Computers](/posts/Language_Of_Computers/).

## A variable is a label on a box

Think of your computer's memory as a very long row of numbered boxes. When you write `age = 42`, the language picks a box, writes `42` into it, and attaches the label `age` to that box. The label is for you; the computer only cares about the box number (the *address*).

```python
age = 42
copy_of_age = age
copy_of_age = copy_of_age + 1

print(age)          # 42
print(copy_of_age)  # 43
```

Here `copy_of_age = age` created a **second box** with its own `42`. Changing one does not touch the other. Numbers, booleans and (in most languages) single characters behave like this. They are *value types*.

{% include article-ads.html %}

## Big things are not copied, they are pointed at

Now try the same experiment with a list:

```python
scores = [1, 2, 3]
other = scores
other.append(4)

print(scores)  # [1, 2, 3, 4]  <- surprise!
print(other)   # [1, 2, 3, 4]
```

Why did `scores` change when we only touched `other`? Because the box labelled `scores` does not hold the list. It holds the **address** of the list, which lives somewhere else in memory. `other = scores` copied the address, not the list. Both labels now point at one list, so changing it through either name changes "both".

![Memory diagram contrasting values and references: on the left, boxes a and b each hold their own copy of the number 42, so changing a leaves b untouched; on the right, boxes scores and other both hold the same address, with arrows pointing at a single list 1, 2, 3, 4, so other.append(4) is visible through scores too](/assets/img/posts/beginner/variables-values-references-memory-diagram.webp)

That address-in-a-box is a **reference** (some languages say *pointer*). Lists, dictionaries, objects, arrays, strings in many languages - anything that can be large or grow - is usually handled by reference. Copying a small address is cheap; copying a million-element list every time you pass it to a function would be ruinously slow.

## The same idea in four languages

The vocabulary differs, but the picture is identical.

**JavaScript** - primitives are values, objects and arrays are references:

```javascript
let a = 10;
let b = a;
b++;              // a is still 10

const user = { name: "Ada" };
const alias = user;
alias.name = "Grace";
console.log(user.name); // "Grace"
```

**C#** - `int`, `double`, `bool` and `struct` are value types; `class` instances are reference types:

```csharp
int x = 5;
int y = x;        // separate copy
y++;              // x == 5

var list1 = new List<int> { 1, 2, 3 };
var list2 = list1;        // same list, two names
list2.Add(4);
Console.WriteLine(list1.Count); // 4
```

**Rust** makes the choice explicit. Assigning a `Vec` *moves* it, so the old name is no longer usable, and borrowing with `&` hands out a reference the compiler tracks:

```rust
let v1 = vec![1, 2, 3];
let v2 = v1;          // v1 moved into v2; using v1 now is a compile error
let r = &v2;          // r is a reference (borrow) to v2's data
println!("{}", r.len());
```

**Python** has only references under the hood, but numbers and strings are *immutable*, so you can never observe sharing: `b = b + 1` builds a brand-new number instead of changing the shared one. Lists and dicts are mutable, which is exactly why the surprise above happens.

{% include article-ads.html %}

## When you really want a copy

If you need an independent list, say so:

```python
other = scores.copy()          # shallow copy: new list, same inner items
import copy
deep  = copy.deepcopy(scores)  # deep copy: new list AND new inner items
```

```javascript
const alias = [...items];              // shallow
const deep  = structuredClone(items);  // deep
```

```csharp
var list2 = new List<int>(list1);      // shallow copy
```

*Shallow* copies the outer container only; if the items inside are themselves references (a list of lists), they are still shared. *Deep* copies recursively. Most of the time shallow is what you want and is much cheaper.

## Passing variables to functions

The same rule explains function arguments. The function receives a copy of whatever is in the box. For a number, that is a copy of the number, so the caller cannot see changes. For a list, it is a copy of the address, so the function can change the caller's list:

```python
def add_one(n):
    n += 1          # local copy only

def add_item(items):
    items.append("x")  # caller's list is changed

count = 1
names = []
add_one(count)
add_item(names)
print(count, names)  # 1 ['x']
```

Reassigning the parameter (`items = []`) inside the function only relabels the local box; it does not affect the caller. Mutating the object it points to does.

## Why this matters

- **Hidden bugs**: a "helper" function quietly modifies the list it was given, and a totally unrelated part of the program breaks.
- **Performance**: understanding that large structures are passed by reference tells you when copying is free and when it is expensive. Our [Performance](/categories/performance/) posts build directly on this.
- **Reading other languages**: once you can spot "value or reference?" you can pick up C, Go, Java or Rust far faster, because they are all answering the same question with different syntax.

## Try it yourself

1. In any language you have installed, create a list, assign it to a second name, change one, and print both.
2. Repeat with a number.
3. Make a real copy and confirm the two names are now independent.

Ten minutes with this exercise will save you hours of debugging later.
