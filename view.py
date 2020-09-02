import os
import sys
import time
import re
import selectors
import fcntl
import selectors
import termios
import socket
import threading
import errno


def atoi(text):
    return int(text) if text.isdigit() else text

def natural_keys(text):
    '''
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    (See Toothy's implementation in the comments)
    '''
    return [ atoi(c) for c in re.split(r'(\d+)', text) ]


class Viewer: 
	maxLengthHexText = 0
	splitAt = 8
	currentLine = 0
	second_buffer = []
	first_buffer = []
	f1 = ""
	f2 = ""
	f1_data = None
	f2_data = None
	opt_txt = ""
	only_changed = False

	_sel = None
	isSynced = False
	meshipc = None

	def __init__(self):
		# Setup terminal
		fd = sys.stdin.fileno()

		oldterm = termios.tcgetattr(fd)
		newattr = oldterm[:]
		newattr[3] = newattr[3] & ~termios.ICANON & ~termios.ECHO
		termios.tcsetattr(fd, termios.TCSANOW, newattr)

		oldflags = fcntl.fcntl(fd, fcntl.F_GETFL)
		fcntl.fcntl(fd, fcntl.F_SETFL, oldflags | os.O_NONBLOCK)

		# Setup socket
		server_address = ('localhost', 10000)
		server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		server.setblocking(False)
		server.bind(server_address)

		self.server = server

	def load(self, f1, f2, opt_txt=""):
		self.f1 = f1
		self.f2 = f2
		self.opt_txt = opt_txt
		data1 = open(f1, "rb")
		data2 = open(f2, "rb")

		self.f1_data = data1.read()
		self.f2_data = data2.read()

		printer.render()
		printer.draw()

	def render(self): # actually load the buffer
		size = 16
		self.second_buffer.clear()
		prevparts = reshape(self.f1_data, size)
		nextparts = reshape(self.f2_data, size)

		longest_prefix = len(hex(len(nextparts) * size)[2:])
		prefixes = [hex(x * size)[2:] for x in range(len(nextparts))]
		adjusted_prefixes = ["0x" + ("0" * (longest_prefix - len(x))) + x for x in prefixes]

		for i in range(len(nextparts)):
			if self.only_changed and prevparts[i] == nextparts[i]:
				continue
			self.second_buffer.append(self._show(adjusted_prefixes[i], prevparts[i], nextparts[i]))
		self.first_buffer = self.second_buffer.copy()

	def draw(self): # print the text out
		rows, columns = self.getsize()
		print(chr(27) + "[2J")
		out = self.opt_txt + "\n"

		file_text = self.f1 + " -> " + self.f2
		surrounding_space = columns - len(file_text)
		centered_text = (" " * (surrounding_space // 2)) + file_text + "\n\n"
		out += centered_text

		targetRows = self.first_buffer[self.currentLine : self.currentLine + rows]

		for ln in targetRows:
			out += ln + "\n"
		sys.stdout.write(out)
		sys.stdout.flush()

	def _show(self, prefix, prev, next):
		visible_length = 0
		out = prefix + "   "
		visible_length += len(out)
		for i in range(len(next)):
			is_same = prev[i] == next[i]
			
			if i % self.splitAt == 0 and i > 0:
				out += "- "
				visible_length += 2
				
			leading = "0" if next[i] < 16 else ""
			hex_byte = leading + hex(next[i])[2:].upper()
			if is_same:
				out += hex_byte + " "
			else:
				out += red(hex_byte) + " "
			visible_length += len(hex_byte) + 1
				
		width = visible_length
		if width > self.maxLengthHexText:
			self.maxLengthHexText = width
		if width < self.maxLengthHexText:
			out += " " * (self.maxLengthHexText - width)
			
		out += "\t"

		for i in range(len(next)):
			out += chr(next[i]) if 32 <= next[i] <= 126 else "."

		return out

	def scrolldown(self, dist=10):
		rows, _ = self.getsize()
		max = len(self.first_buffer) - rows  # lowest the buffer cursor can go, after accounting for displayed rows

		if self.currentLine == max:
			return

		if self.currentLine + dist <= max:
			self.currentLine += dist
		else:
			self.currentLine = max

		self.draw()

	def scrollup(self, dist=10):
		if self.currentLine == 0:
			return

		if self.currentLine - dist >= 0:
			self.currentLine -= dist
		else:
			self.currentLine = 0
		self.draw()

	def getsize(self):
		rows, columns = os.popen('stty size', 'r').read().split()
		return (int(rows) - 5, int(columns))

	def processKeyboardKey(self, stdin, mask):
		global current_file, printer, file_count
		c = stdin.read(8)
		if c:
			if c == "s":  # Sync to other instances
				self.isSynced = not self.isSynced
				if self.isSynced:
					self.meshipc = MeshIPC()
					self._sel.register()
				else:
					self._sel.unregister()

			if c == "\x1b[B":  # Up arrow
				printer.scrolldown()
			if c == "\x1b[A":  # Up arrow
				printer.scrollup()
			if c == "\x1b[6~":  # Pg Down
				rows, _ = printer.getsize()
				printer.scrolldown(rows)
			if c == "\x1b[5~":  # Pg Up
				rows, _ = printer.getsize()
				printer.scrollup(rows)
			if c == ".":
				printer.only_changed = not printer.only_changed
				printer.render()
				printer.draw()
			if c == "+":
				if current_file + 2 >= file_count:
					return
				current_file += 1
				printer.load(sys.argv[1] + "//" + patterened_files[current_file], sys.argv[1] + "//" + patterened_files[current_file + 1], processed_opcodes[current_file])
			if c == "-":
				if current_file == 0:
					return
				current_file -= 1
				printer.load(sys.argv[1] + "//" + patterened_files[current_file], sys.argv[1] + "//" + patterened_files[current_file + 1], processed_opcodes[current_file])
			#print(repr(c))
			#print(str(c))

	def process(self):
		mysel = selectors.DefaultSelector()
		mysel.register(sys.stdin, selectors.EVENT_READ, self.processKeyboardKey)
		self.sel_ = mysel

		while True:
			# print('waiting for I/O')
			for key, mask in mysel.select():
				callback = key.data
				callback(key.fileobj, mask)

			
	
def reshape(lst, n):
	return [lst[i*n:(i+1)*n] for i in range(len(lst)//n)]


def red(text):
	return '\u001b[38;5;1m' + text + '\u001b[0m'




# files = os.listdir(sys.argv[1])
# patterened_files = [x for x in files if x.startswith(sys.argv[2])]
# patterened_files.sort(key=natural_keys)
# current_file = 0
# file_count = len(patterened_files)
#
# opcodetext = [0x0, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x15, 0x15, 0x15, 0x15, 0x15, 0x12, 0x3, 0x3, 0x3, 0x3, 0x3, 0x3, 0x3, 0x5, 0x13, 0x12, 0x4, 0x16, 0x13, 0x12, 0x4, 0x3, 0x16, 0x13, 0x12, 0x4, 0x3, 0x3, 0x5, 0x3, 0xb, 0xb, 0x7, 0x3, 0x15, 0x14, 0x13, 0x12, 0x4, 0x13, 0x12, 0x4, 0x3, 0x13, 0x12, 0x4, 0x3, 0x7, 0x3, 0x5, 0x3, 0xb, 0xb, 0x3, 0x15, 0x3, 0x13, 0x12, 0x4, 0x13, 0x12, 0x4, 0x3, 0x13, 0x12, 0x4, 0x3, 0x1, 0x3, 0x5, 0x3, 0xb, 0xb, 0x3, 0x15, 0x3, 0x13, 0x12, 0x4, 0x13, 0x12, 0x4, 0x3, 0x13, 0x12, 0x4, 0x3, 0x2, 0x3, 0x5, 0x3, 0xb, 0xb, 0x3, 0x15, 0x3, 0x13, 0x12, 0x4, 0x13, 0x12, 0x4, 0x3, 0x13, 0x12, 0x4, 0x3, 0x3, 0x5, 0x3, 0xb, 0xb, 0x3, 0x15, 0x3, 0x13, 0x12, 0x4, 0x13, 0x12, 0x4, 0x3, 0x13, 0x12, 0x4, 0x3, 0x3, 0x5, 0x3, 0xb, 0xb, 0x3, 0x15, 0x3, 0x14, 0x13, 0x12, 0x4, 0x13, 0x12, 0x4, 0x3, 0x13, 0x12, 0x4, 0x3, 0x3, 0x5, 0x3, 0xb, 0xb, 0x3, 0x15, 0x3, 0x13, 0x12, 0x4, 0x13, 0x12, 0x4, 0x3, 0x13, 0x12, 0x4, 0x3, 0x15, 0x3, 0x5, 0x3, 0xb, 0xb, 0x3, 0x15, 0x3, 0x11, 0x5, 0x11]
# processed_opcodes = ["Opcode: " + hex(x) for x in opcodetext]
#
# printer = Viewer()
# printer.load(sys.argv[1] + "//" + patterened_files[current_file], sys.argv[1] + "//" + patterened_files[current_file + 1], processed_opcodes[current_file])
#
# printer.process()

CLIENT_ONLY = 0
SERVER_ONLY = 1


class MeshIPC:
	i_am_server = False
	clients = []
	socket = None
	_sel = None

	def __init__(self, sel):
		self._sel = sel
		self.connect()

	def __del__(self):
		if self._sel and self.socket:
			self._sel.unregister(self.socket)

		if self.socket:
			self.socket.close()

	def connect(self):
		if self.socket:
			self._sel.unregister(self.socket)
		created_server = self.server()
		self.i_am_server = created_server

		if not created_server:
			self.client()

	def server(self):
		server_address = ('localhost', 10000)
		server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		server.setblocking(True)
		try:
			server.bind(server_address)
			server.listen(1)
		except socket.error as e:
			return False



		self.socket = server
		thread = threading.Thread(None, self.accept, None, (server,))
		thread.setDaemon(True)
		thread.start()
		print ("Im a server")

		return True

	def client(self):
		server_address = ('localhost', 10000)
		client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		client.connect(server_address)
		client.setblocking(False)
		self.socket = client
		self._sel.register(client, selectors.EVENT_READ, lambda _, __, ipc=self: print(self.get()))

	def send(self, data):
		for con in self.clients:
			try:
				con.sendall(data.encode('utf-8'))
			except IOError as e:
				if e.errno == errno.EPIPE:
					# client disconnected.
					self.clients.remove(con)
				else:
					print(e)
					break

	def accept(self, server):  # Runs on another thread
		while True:
			connection, client_address = server.accept()
			connection.setblocking(False)
			self.clients.append(connection)

	def get(self):
		try:
			data = self.socket.recv(4096)
			if data == b'':
				self.connect()
				return ""
			return data
		except OSError as e:
			if OSError.errno == errno.EAGAIN:
				self.connect()
				return ""

# # Setup terminal
fd = sys.stdin.fileno()

oldterm = termios.tcgetattr(fd)
newattr = oldterm[:]
newattr[3] = newattr[3] & ~termios.ICANON & ~termios.ECHO
termios.tcsetattr(fd, termios.TCSANOW, newattr)

oldflags = fcntl.fcntl(fd, fcntl.F_GETFL)
fcntl.fcntl(fd, fcntl.F_SETFL, oldflags | os.O_NONBLOCK)
sel = selectors.DefaultSelector()
tester = MeshIPC(sel)


def keyboard(x, _):
	data = x.read(8)
	if tester.i_am_server:
		tester.send(data)
	print(data)


sel.register(sys.stdin, selectors.EVENT_READ, keyboard)

while True:
	for key, mask in sel.select():
		callback = key.data
		callback(key.fileobj, mask)

