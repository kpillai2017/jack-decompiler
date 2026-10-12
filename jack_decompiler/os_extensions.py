"""Public companion OS additions; separate from standard nand2tetris APIs."""

DECLARATIONS = {
    "Memory": ("function void fill(int address, int count, int value)", "function void copy(int source, int destination, int count)", "function void move(int source, int destination, int count)"),
    "Screen": ("function void drawBitmap(int x, int y, int width, int height, Array bitmap)", "function void drawSprite(int x, int y, int width, int height, Array bitmap, Array mask)", "function void captureBitmap(int x, int y, int width, int height, Array buffer)", "function void drawVertical(int x, int y1, int y2)"),
    "Output": ("function int cursorRow()", "function int cursorColumn()"),
    "String": ("method int capacity()", "method void clear()", "method boolean hasCapacity(int count)", "method String appendString(String other)", "method boolean equals(String other)", "method int indexOf(int c)", "method String substring(int start, int count)", "method String copy()", "method boolean isInteger()"),
    "Math": ("function int clamp(int value, int minimum, int maximum)", "function int sign(int value)", "function int mod(int value, int divisor)", "function int shiftLeft(int value, int count)", "function int shiftRight(int value, int count)", "function int shiftRightUnsigned(int value, int count)"),
    "Input": ("function void init()", "function void update()", "function int key()", "function int pressed()", "function int released()"),
    "Random": ("constructor Random new(int seed)", "method int next()", "method int range(int limit)", "method void dispose()"),
    "IntQueue": ("constructor IntQueue new(int cap)", "method void enqueue(int value)", "method int dequeue()", "method boolean isEmpty()", "method boolean isFull()", "method int length()", "method void clear()", "method void dispose()"),
    "IntStack": ("constructor IntStack new(int cap)", "method void push(int value)", "method int pop()", "method int peek()", "method boolean isEmpty()", "method boolean isFull()", "method int length()", "method void clear()", "method void dispose()"),
    "Console": ("function void printAt(int row, int column, String text)", "function void clearLine(int row)", "function void clearRegion(int row, int column, int rows, int columns)", "function void scrollUp(int lines)", "function void printPaddedInt(int value, int width)"),
    "Timer": ("constructor Timer new(int units)", "method void tick()", "method void advance(int units)", "method int remaining()", "method boolean expired()", "method void reset()", "method void restart(int units)", "method void dispose()"),
    "Clock": ("function boolean supported()", "function int now()", "function int elapsed(int start)"),
}
