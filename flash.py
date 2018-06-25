#!/usr/bin/env python

from __future__ import division, print_function
import struct
import time
import sys
import os
import argparse

from HondaECU import *

def do_validation(binfile, fix=False):
	print("===============================================")
	if fix:
		print("Fixing bin file checksum")
	else:
		print("Validating bin file checksum")
	with open(binfile, "rb") as fbin:
		byts, fcksum, ccksum, fixed = validate_checksum(bytearray(fbin.read(os.path.getsize(binfile))), fix)
		if fixed:
			status = "fixed"
		elif fcksum == ccksum:
			status = "good"
		else:
			status = "bad"
		print("  file checksum: %s" % fcksum)
		print("  calculated checksum: %s" % ccksum)
		print("  status: %s" % status)
		return byts, fcksum, ccksum, fixed

def do_read_flash(ecu, binfile, rom_size):
	maxbyte = 1024 * rom_size
	nbyte = 0
	readsize = 8
	with open(binfile, "wb") as fbin:
		t = time.time()
		while nbyte < maxbyte:
			info = ecu.send_command([0x82, 0x82, 0x00], [int(nbyte/65536)] + [b for b in struct.pack("<H", nbyte % 65536)] + [readsize], debug=args.debug)
			fbin.write(info[2])
			fbin.flush()
			nbyte += readsize
			if nbyte % 64 == 0:
				sys.stdout.write(".")
				sys.stdout.flush()
			if nbyte % 1024 == 0:
				n = time.time()
				sys.stdout.write(" %dkb %.02fbps\n" % (int(nbyte/1024),1024/(n-t)))
				t = n

def do_write_flash(ecu, byts):
	writesize = 128
	maxi = len(byts)/128
	i = 0
	while i < maxi:
		a1 = [s for s in struct.pack(">H",8*i)]
		a2 = [s for s in struct.pack(">H",8*(i+1))]
		a3 = [s for s in struct.pack(">H",8*(i+2))]
		d1 = list(byts[((i+0)*128):((i+1)*128)])
		d2 = list(byts[((i+1)*128):((i+2)*128)])
		c1 = checksum8bitHonda(a1+a2+d1)
		c2 = checksum8bitHonda(a2+a3+d2)
		s1 = 0xff-struct.pack(">H",sum(d1))[0]
		s2 = 0xff-struct.pack(">H",sum(d2))[0]
		x1 = [0x01, 0x06] + a1 + d1 + a2 + [s1, c1]
		x2 = [0x01, 0x06] + a2 + d2 + a3 + [s2, c2]
		ecu.send_command([0x7e], x1, debug=args.debug)
		ecu.send_command([0x7e], x2, debug=args.debug)
		ecu.send_command([0x7e], [0x01, 0x08], debug=args.debug)
		i += 2
		time.sleep(2)

if __name__ == '__main__':

	parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('mode', choices=["read","write","recover","validate_checksum","fix_checksum"], help="ECU mode")
	parser.add_argument('binfile', help="name of bin to read or write")
	parser.add_argument('--rom-size', default=256, type=int, help="size of ECU rom in kilobytes")
	db_grp = parser.add_argument_group('debugging options')
	db_grp.add_argument('--skip-power-check', action='store_true', help="don't test for k-line activity")
	db_grp.add_argument('--fix-checksum', action='store_true', help="fix checksum before write/recover")
	db_grp.add_argument('--debug', action='store_true', help="turn on debugging output")
	args = parser.parse_args()

	if os.path.isabs(args.binfile):
		binfile = args.binfile
	else:
		binfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.binfile)

	ret = 1
	if args.mode != "read":
		byts, fcksum, ccksum, fixed = do_validation(binfile, args.mode == "fix_checksum" or args.fix_checksum)
		if (fcksum == ccksum or fixed) and args.mode in ["recover","write"]:
			ret = 0
		else:
			ret = -1
	else:
		ret = 0

	if ret == 0:

		ecu = HondaECU()
		ecu.setup()

		if not args.skip_power_check:
			print("===============================================")
			# In order to read flash we must send commands while the ECU's
			# bootloader is still active which is right after the bike powers up
			if ecu.kline():
				print("Turn off bike")
				while ecu.kline():
					time.sleep(.1)
			print("Turn on bike")
			while not ecu.kline():
				time.sleep(.1)
			time.sleep(.5)

		print("===============================================")
		print("Initializing ECU communications")
		ecu.init(debug=args.debug)
		ecu.send_command([0x72],[0x00, 0xf0], debug=args.debug)

		if args.mode == "read":
			print("===============================================")
			print("Entering Boot Mode")
			ecu.send_command([0x27],[0xe0, 0x48, 0x65, 0x6c, 0x6c, 0x6f, 0x48, 0x6f], debug=args.debug)
			ecu.send_command([0x27],[0xe0, 0x77, 0x41, 0x72, 0x65, 0x59, 0x6f, 0x75], debug=args.debug)
			print("===============================================")
			print("Dumping ECU to bin file")
			do_read_flash(ecu, binfile, args.rom_size)
			do_validation(binfile)

		elif args.mode == "recover":
			print("===============================================")
			print("Recovering ECU")
			ecu.do_init_recover(debug=args.debug)
			ecu.send_command([0x72],[0x00, 0xf1], debug=args.debug)
			ecu.send_command([0x27],[0x00, 0x9f, 0x00], debug=args.debug)
			ecu.do_pre_write(debug=args.debug)
			ecu.do_pre_write_wait(debug=args.debug)
			ecu.send_command([0x7e], [0x01, 0xa0, 0x02], debug=args.debug)
			do_write_flash(ecu, byts)

		elif args.mode == "write":
			print("===============================================")
			print("Writing bin file to ECU")
			ecu.do_init_write(debug=args.debug)
			ecu.do_pre_write(debug=args.debug)
			ecu.do_pre_write_wait(debug=args.debug)
			do_write_flash(ecu, byts)
			ecu.send_command([0x7e], [0x01, 0x01, 0x00], debug=args.debug)
			ecu.send_command([0x7e], [0x01, 0x09], debug=args.debug)
			ecu.send_command([0x7e], [0x01, 0x01, 0x00], debug=args.debug)
			ecu.send_command([0x7e], [0x01, 0x0a], debug=args.debug)
			ecu.send_command([0x7e], [0x01, 0x01, 0x00], debug=args.debug)
			ecu.send_command([0x7e], [0x01, 0x0c], debug=args.debug)
			ecu.send_command([0x7e], [0x01, 0x01, 0x00], debug=args.debug)
			ecu.send_command([0x7e], [0x01, 0x0d], debug=args.debug)
			ecu.send_command([0x7e], [0x01, 0x01, 0x00], debug=args.debug)


	print("===============================================")
	sys.exit(ret)
