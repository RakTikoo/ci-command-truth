include extra.mk

test:
	echo ok

%.o: %.c
	cc -c $<

.c.o:
	cc -c $<

define TEMPLATE
fake:
	echo nope
endef

.PHONY: test # main test target
