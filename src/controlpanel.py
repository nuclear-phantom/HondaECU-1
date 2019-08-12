import sys
import os
import platform

import json
import time

from pydispatch import dispatcher

import wx
import wx.lib.buttons as buttons
import wx.lib.agw.labelbook as LB

import EnhancedStatusBar as ESB

from frames.info import HondaECU_InfoPanel
from frames.data import HondaECU_DatalogPanel
from frames.error import HondaECU_ErrorPanel
from frames.flash import HondaECU_FlashPanel
from frames.hrcsettings import HondaECU_HRCDataSettingsPanel
from frames.eeprom import HondaECU_EEPROMPanel

import usb.util

from threads.kline import KlineWorker
from threads.usb import USBMonitor

import tarfile

from ecmids import ECM_IDs

from eculib.honda import ECUSTATE, checksum8bitHonda

from appdirs import *
import configparser

class CharValidator(wx.Validator):

	def __init__(self, flag):
		wx.Validator.__init__(self)
		self.flag = flag
		self.Bind(wx.EVT_CHAR, self.OnChar)

	def Clone(self):
		return CharValidator(self.flag)

	def Validate(self, win):
		return True

	def TransferToWindow(self):
		return True

	def TransferFromWindow(self):
		return True

	def OnChar(self, event):
		keycode = int(event.GetKeyCode())
		if keycode in [wx.WXK_BACK, wx.WXK_DELETE]:
			pass
		elif keycode < 256:
			self.key = chr(keycode)
			if not key in string.hexdigits:
				return
		event.Skip()

class PasswordDialog(wx.Dialog):

	def __init__(self, parent):
		self.parent = parent
		super(PasswordDialog, self).__init__(parent)

		self.secure = False

		panel = wx.Panel(self)

		self.g_sizer = wx.GridBagSizer()

		self.cancel = wx.Button(panel, label="Cancel")
		self.ok = wx.Button(panel, label="Ok")

		self.font2 = self.GetFont().Bold()
		self.font2.SetPointSize(self.font2.GetPointSize()*1.5)
		self.msg1 = wx.StaticText(panel,label="Turn OFF ECU",style=wx.ALIGN_CENTRE_HORIZONTAL|wx.ALIGN_CENTRE_VERTICAL)
		self.msg1.SetFont(self.font2)
		self.msg1.Hide()

		self.passboxp = wx.Panel(panel)
		self.passp = wx.Panel(self.passboxp)
		self.passboxsizer = wx.StaticBoxSizer(wx.VERTICAL, self.passboxp, "Password")
		self.passpsizer = wx.GridBagSizer()
		self.passp.SetSizer(self.passpsizer)
		self.passboxp.SetSizer(self.passboxsizer)
		self.password_chars = []
		for i, val in enumerate([0x48, 0x65, 0x6c, 0x6c, 0x6f, 0x48, 0x6f, 0x77, 0x41, 0x72, 0x65, 0x59, 0x6f, 0x75]):
			H = "%2X" % val
			self.password_chars.append([
				wx.StaticText(self.passp, size=(32,-1), label="%s" % chr(val), style=wx.ALIGN_CENTRE_HORIZONTAL),
				wx.TextCtrl(self.passp, size=(32,32), value=H, validator=CharValidator("hexdigits"))
			])
			self.password_chars[-1][0].Disable()
			self.password_chars[-1][1].SetMaxLength(2)
			self.password_chars[-1][1].SetHint(H)
			self.Bind(wx.EVT_TEXT, lambda x, index=i: self.OnPassByte(x, index), self.password_chars[-1][1])
			self.passpsizer.Add(self.password_chars[-1][1], pos=(0,i), flag=wx.LEFT|wx.RIGHT, border=1)
			self.passpsizer.Add(self.password_chars[-1][0], pos=(1,i), flag=wx.LEFT|wx.RIGHT, border=1)
		self.passboxsizer.Add(self.passp, 0, wx.ALL, border=10)

		self.g_sizer.Add(self.passboxp, span=(1,4), pos=(0,0), flag=wx.TOP|wx.EXPAND, border=5)
		self.g_sizer.Add(self.cancel, pos=(1,1), flag=wx.ALL, border=10)
		self.g_sizer.Add(self.ok, pos=(1,2), flag=wx.ALL, border=10)

		mainsizer = wx.BoxSizer(wx.VERTICAL)
		mainsizer.Add(self.g_sizer, 1, wx.EXPAND)
		mainsizer.Add(self.msg1, 1, wx.EXPAND|wx.TOP, border=50)
		mainsizer.SetSizeHints(self)
		self.SetSizer(mainsizer)

		self.cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
		self.ok.Bind(wx.EVT_BUTTON, self.OnOk)

		self.Center()
		self.Layout()

		dispatcher.connect(self.KlineWorkerHandler, signal="KlineWorker", sender=dispatcher.Any)

	def KlineWorkerHandler(self, info, value):
		if info == "state":
			if value == ECUSTATE.SECURE:
				if self.secure:
					self.secure = False
					self.Hide()
			elif value == ECUSTATE.OFF:
				if self.secure:
					self.msg1.SetLabel("Turn On ECU")
					self.Layout()

	def _Show(self, msg1="Turn Off ECU"):
		self.secure = False
		self.msg1.SetLabel(msg1)
		self.msg1.Hide()
		self.passboxp.Show()
		self.ok.Show()
		self.cancel.Show()
		self.Show()
		self.Layout()

	def OnOk(self, event):
		self.secure = True
		self.passboxp.Hide()
		self.ok.Hide()
		self.cancel.Hide()
		self.msg1.Show()
		self.msg1.SetLabel("Turn Off ECU")
		self.Layout()
		passwd = [int(P[1].GetValue(),16) for P in self.password_chars]
		dispatcher.send(signal="sendpassword", sender=self, passwd=passwd)

	def OnCancel(self, event):
		self.Hide()

class SettingsDialog(wx.Dialog):

	def __init__(self, parent):
		self.parent = parent
		super(SettingsDialog, self).__init__(parent, title="HondaECU Settings")

		panel = wx.Panel(self)

		g_sizer = wx.GridBagSizer()

		self.retriesl = wx.StaticText(panel, label="Retries:", style=wx.ALIGN_RIGHT)
		self.retries = wx.TextCtrl(panel)
		self.retriesu = wx.StaticText(panel, label="attempts", style=wx.ALIGN_LEFT)
		self.retries.SetValue(self.parent.config["DEFAULT"]["retries"])

		self.timeoutl = wx.StaticText(panel, label="Timeout:", style=wx.ALIGN_RIGHT)
		self.timeout = wx.TextCtrl(panel)
		self.timeoutu = wx.StaticText(panel, label="seconds", style=wx.ALIGN_LEFT)
		self.timeout.SetValue(self.parent.config["DEFAULT"]["timeout"])

		self.klinemethods = ["loopback_ping"]
		self.klinedetectl = wx.StaticText(panel, label="Kline Detection:", style=wx.ALIGN_RIGHT)
		self.klinedetect = wx.ComboBox(panel, value="loopback_ping", choices=self.klinemethods, style=wx.CB_READONLY)
		self.klinedetect.SetValue(self.parent.config["DEFAULT"]["klinemethod"])

		self.cancel = wx.Button(panel, label="Cancel")
		self.ok = wx.Button(panel, label="Ok")

		g_sizer.Add(self.retriesl, span=(1,2), pos=(0,1), flag=wx.TOP|wx.EXPAND, border=5)
		g_sizer.Add(self.retries, pos=(0,3), flag=wx.TOP|wx.LEFT|wx.RIGHT, border=5)
		g_sizer.Add(self.retriesu, span=(1,2), pos=(0,4), flag=wx.TOP|wx.EXPAND, border=5)

		g_sizer.Add(self.timeoutl, span=(1,2), pos=(1,1), flag=wx.EXPAND)
		g_sizer.Add(self.timeout, pos=(1,3), flag=wx.LEFT|wx.RIGHT, border=5)
		g_sizer.Add(self.timeoutu, span=(1,2), pos=(1,4), flag=wx.EXPAND)

		g_sizer.Add(self.klinedetectl, span=(1,2), pos=(2,1), flag=wx.EXPAND)
		g_sizer.Add(self.klinedetect, pos=(2,3), flag=wx.LEFT|wx.RIGHT, border=5)

		g_sizer.Add(self.cancel, span=(1,2), pos=(3,0), flag=wx.ALL, border=10)
		g_sizer.Add(self.ok, span=(1,2), pos=(3,4), flag=wx.ALL, border=10)

		mainsizer = wx.BoxSizer(wx.VERTICAL)
		mainsizer.Add(g_sizer, 1, wx.EXPAND)
		mainsizer.SetSizeHints(self)
		self.SetSizer(mainsizer)

		self.cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
		self.ok.Bind(wx.EVT_BUTTON, self.OnOk)

		self.Center()
		self.Layout()

	def OnOk(self, event):
		self.parent.config["DEFAULT"]["retries"] = self.retries.GetValue()
		self.parent.config["DEFAULT"]["timeout"] = self.timeout.GetValue()
		self.parent.config["DEFAULT"]["klinemethod"] = self.klinedetect.GetValue()
		dispatcher.send(signal="settings", sender=self, config=self.parent.config)
		self.Hide()

	def OnCancel(self, event):
		self.Hide()

class HondaECU_AppButton(buttons.ThemedGenBitmapTextButton):

	def __init__(self, appid, enablestates, *args, **kwargs):
		self.appid = appid
		self.enablestates = enablestates
		buttons.ThemedGenBitmapTextButton.__init__(self, *args,**kwargs)
		self.SetInitialSize((128,64))

	def DrawLabel(self, dc, width, height, dx=0, dy=0):
		bmp = self.bmpLabel
		if bmp is not None:
			if self.bmpDisabled and not self.IsEnabled():
				bmp = self.bmpDisabled
			if self.bmpFocus and self.hasFocus:
				bmp = self.bmpFocus
			if self.bmpSelected and not self.up:
				bmp = self.bmpSelected
			bw,bh = bmp.GetWidth(), bmp.GetHeight()
			if not self.up:
				dx = dy = self.labelDelta
			hasMask = bmp.GetMask() is not None
		else:
			bw = bh = 0
			hasMask = False

		dc.SetFont(self.GetFont())
		if self.IsEnabled():
			dc.SetTextForeground(self.GetForegroundColour())
		else:
			dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))

		label = self.GetLabel()
		tw, th = dc.GetTextExtent(label)
		if not self.up:
			dx = dy = self.labelDelta

		if bmp is not None:
			dc.DrawBitmap(bmp, (width-bw)/2, (height-bh-th-4)/2, hasMask)
		dc.DrawText(label, (width-tw)/2, (height+bh-th+4)/2)

class HondaECU_LogPanel(wx.Frame):

	def __init__(self, parent):
		self.auto = True
		wx.Frame.__init__(self, parent, title="HondaECU :: Debug Log", size=(640,480))
		self.SetMinSize((640,480))

		self.menubar = wx.MenuBar()
		self.SetMenuBar(self.menubar)
		fileMenu = wx.Menu()
		self.menubar.Append(fileMenu, '&File')
		saveItem = wx.MenuItem(fileMenu, wx.ID_SAVEAS, '&Save As\tCtrl+S')
		self.Bind(wx.EVT_MENU, self.OnSave, saveItem)
		fileMenu.Append(saveItem)
		fileMenu.AppendSeparator()
		quitItem = wx.MenuItem(fileMenu, wx.ID_EXIT, '&Quit\tCtrl+Q')
		self.Bind(wx.EVT_MENU, self.OnClose, quitItem)
		fileMenu.Append(quitItem)
		viewMenu = wx.Menu()
		self.menubar.Append(viewMenu, '&View')
		self.autoscrollItem = viewMenu.AppendCheckItem(wx.ID_ANY, 'Auto scroll log')
		self.autoscrollItem.Check()
		self.logText = wx.TextCtrl(self, style = wx.TE_MULTILINE|wx.TE_READONLY|wx.HSCROLL|wx.TE_RICH)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(self.logText, 1, wx.EXPAND|wx.ALL, 5)
		self.SetSizer(sizer)
		self.Bind(wx.EVT_CLOSE, self.OnClose)
		self.Layout()
		# sizer.Fit(self)
		self.Center()
		self.starttime = time.time()
		wx.CallAfter(dispatcher.connect, self.ECUDebugHandler, signal="ecu.debug", sender=dispatcher.Any)

	def OnSave(self, event):
		with wx.FileDialog(self, "Save debug log", wildcard="Debug log files (*.txt)|*.txt", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
			if fileDialog.ShowModal() == wx.ID_CANCEL:
				return
			pathname = fileDialog.GetPath()
			try:
				with open(pathname, 'w') as file:
					file.write(self.logText.GetValue())
			except IOError:
				print("Cannot save current data in file '%s'." % pathname)

	def OnClose(self, event):
		self.Hide()

	def ECUDebugHandler(self, msg):
		msg = "[%.4f] %s\n" % (time.time()-self.starttime, msg)
		if self.autoscrollItem.IsChecked():
			wx.CallAfter(self.logText.AppendText, msg)
		else:
			wx.CallAfter(self.logText.WriteText, msg)

class HondaECU_ControlPanel(wx.Frame):

	def __init__(self, version_full, nobins=False, restrictions=None, force_restrictions=False):
		self.prefsdir = user_data_dir("HondaECU","MCUInnovationsInc")
		if not os.path.exists(self.prefsdir):
			os.makedirs(self.prefsdir)
		self.configfile = os.path.join(self.prefsdir,'hondaecu.ini')
		self.config = configparser.ConfigParser()
		if os.path.isfile(self.configfile):
			self.config.read(self.configfile)
		if not "retries" in self.config['DEFAULT']:
			self.config['DEFAULT']['retries'] = "1"
		if not "timeout" in self.config['DEFAULT']:
			self.config['DEFAULT']['timeout'] = "0.1"
		if not "klinemethod" in self.config['DEFAULT']:
			self.config['DEFAULT']['klinemethod'] = "loopback_ping"
		else:
			if self.config['DEFAULT']['klinemethod'] == "poll_modem_status":
				self.config['DEFAULT']['klinemethod'] = "loopback_ping"
		with open(self.configfile, 'w') as configfile:
			self.config.write(configfile)
		self.nobins = nobins
		self.restrictions = restrictions
		self.force_restrictions = force_restrictions
		self.run = True
		self.active_ftdi_device = None
		self.ftdi_devices = {}
		self.warned = []
		self.__clear_data()

		if getattr(sys, 'frozen', False):
			self.basepath = sys._MEIPASS
		else:
			self.basepath = os.path.dirname(os.path.realpath(__file__))

		self.version_full = version_full
		self.version_short = self.version_full.split("-")[0]

		self.apps = {
			"flash": {
				"label":"Flash",
				"panel":HondaECU_FlashPanel,
			},
			# "eeprom": {
			# 	"label":"EEPROM",
			# 	"panel":HondaECU_EEPROMPanel,
			# },
			# "hrc": {
			# 	"label":"HRC Data Settings",
			# 	"panel":HondaECU_HRCDataSettingsPanel,
			# },
			"data": {
				"label":"Data Logging",
				"panel":HondaECU_DatalogPanel,
			},
			"dtc": {
				"label":"Trouble Codes",
				"panel":HondaECU_ErrorPanel,
			},
		}
		self.appanels = {}

		wx.Frame.__init__(self, None, title="HondaECU %s" % (self.version_short), style=wx.DEFAULT_FRAME_STYLE ^ wx.RESIZE_BORDER, size=(500,300))

		ib = wx.IconBundle()
		ib.AddIcon(os.path.join(self.basepath,"images","honda.ico"))
		self.SetIcons(ib)

		self.menubar = wx.MenuBar()
		self.SetMenuBar(self.menubar)
		fileMenu = wx.Menu()
		self.menubar.Append(fileMenu, '&File')
		settingsItem = wx.MenuItem(fileMenu, wx.ID_ANY, 'Settings')
		self.Bind(wx.EVT_MENU, self.OnSettings, settingsItem)
		fileMenu.Append(settingsItem)
		fileMenu.AppendSeparator()
		quitItem = wx.MenuItem(fileMenu, wx.ID_EXIT, '&Quit\tCtrl+Q')
		self.Bind(wx.EVT_MENU, self.OnClose, quitItem)
		fileMenu.Append(quitItem)
		helpMenu = wx.Menu()
		self.menubar.Append(helpMenu, '&Help')
		debugItem = wx.MenuItem(helpMenu, wx.ID_ANY, 'Show debug log')
		self.Bind(wx.EVT_MENU, self.OnDebug, debugItem)
		helpMenu.Append(debugItem)
		helpMenu.AppendSeparator()
		detectmapItem = wx.MenuItem(helpMenu, wx.ID_ANY, 'Detect map id')
		self.Bind(wx.EVT_MENU, self.OnDetectMap, detectmapItem)
		helpMenu.Append(detectmapItem)
		checksumItem = wx.MenuItem(helpMenu, wx.ID_ANY, 'Validate bin checksum')
		self.Bind(wx.EVT_MENU, self.OnBinChecksum, checksumItem)
		helpMenu.Append(checksumItem)

		self.statusicons = [
			wx.Image(os.path.join(self.basepath, "images/bullet_black.png"), wx.BITMAP_TYPE_ANY).ConvertToBitmap(),
			wx.Image(os.path.join(self.basepath, "images/bullet_yellow.png"), wx.BITMAP_TYPE_ANY).ConvertToBitmap(),
			wx.Image(os.path.join(self.basepath, "images/bullet_green.png"), wx.BITMAP_TYPE_ANY).ConvertToBitmap(),
			wx.Image(os.path.join(self.basepath, "images/bullet_blue.png"), wx.BITMAP_TYPE_ANY).ConvertToBitmap(),
			wx.Image(os.path.join(self.basepath, "images/bullet_purple.png"), wx.BITMAP_TYPE_ANY).ConvertToBitmap(),
			wx.Image(os.path.join(self.basepath, "images/bullet_red.png"), wx.BITMAP_TYPE_ANY).ConvertToBitmap()
		]

		self.statusbar = ESB.EnhancedStatusBar(self, -1)
		self.SetStatusBar(self.statusbar)
		self.statusbar.SetSize((-1, 28))
		self.statusicon = wx.StaticBitmap(self.statusbar)
		self.statusicon.SetBitmap(self.statusicons[0])
		self.ecmidl = wx.StaticText(self.statusbar)
		self.flashcountl = wx.StaticText(self.statusbar)
		self.dtccountl = wx.StaticText(self.statusbar)
		self.statusbar.SetFieldsCount(4)
		self.statusbar.SetStatusWidths([32, 170, 130, 110])
		self.statusbar.AddWidget(self.statusicon, pos=0)
		self.statusbar.AddWidget(self.ecmidl, pos=1, horizontalalignment=ESB.ESB_ALIGN_LEFT)
		self.statusbar.AddWidget(self.flashcountl, pos=2, horizontalalignment=ESB.ESB_ALIGN_LEFT)
		self.statusbar.AddWidget(self.dtccountl, pos=3, horizontalalignment=ESB.ESB_ALIGN_LEFT)
		self.statusbar.SetStatusStyles([wx.SB_SUNKEN,wx.SB_SUNKEN,wx.SB_SUNKEN,wx.SB_SUNKEN])

		self.outerp = wx.Panel(self)

		self.adapterboxp = wx.Panel(self.outerp)
		self.securebutton = wx.Button(self.adapterboxp, label="Secure Mode")
		self.adapterboxsizer = wx.StaticBoxSizer(wx.HORIZONTAL, self.adapterboxp, "FTDI Devices:")
		self.adapterboxp.SetSizer(self.adapterboxsizer)
		self.adapterlist = wx.Choice(self.adapterboxp, wx.ID_ANY, size=(-1,32))
		self.adapterboxsizer.Add(self.adapterlist, 1, wx.ALL|wx.EXPAND, border=5)
		self.adapterboxsizer.Add(self.securebutton, 0, wx.ALL, border=5)

		self.labelbook = LB.LabelBook(self.outerp, agwStyle=LB.INB_FIT_LABELTEXT|LB.INB_LEFT|LB.INB_DRAW_SHADOW|LB.INB_GRADIENT_BACKGROUND)

		self.bookpages = {}
		maxdims = [0,0]
		for a,d in self.apps.items():
			enablestates = None
			if "enable" in self.apps[a]:
				enablestates = self.apps[a]["enable"]
			self.bookpages[a] = d["panel"](self, a, self.apps[a], enablestates)
			x,y = self.bookpages[a].GetSize()
			if x > maxdims[0]:
				maxdims[0] = x
			if y > maxdims[1]:
				maxdims[1] = y
			self.labelbook.AddPage(self.bookpages[a], d["label"], False)
		for k in self.bookpages.keys():
			self.bookpages[k].SetMinSize(maxdims)

		self.modelp = wx.Panel(self.outerp, style=wx.BORDER_SUNKEN)
		self.modelbox = wx.BoxSizer(wx.VERTICAL)
		self.modell = wx.StaticText(self.modelp, label="", style=wx.ALIGN_CENTRE_HORIZONTAL|wx.ALIGN_CENTRE_VERTICAL)
		self.ecupnl = wx.StaticText(self.modelp, label="", style=wx.ALIGN_CENTRE_HORIZONTAL|wx.ALIGN_CENTRE_VERTICAL)
		font1 = self.GetFont().Bold()
		font2 = self.GetFont().Bold()
		font1.SetPointSize(font1.GetPointSize()*1.25)
		font2.SetPointSize(font2.GetPointSize()*2)
		self.modell.SetFont(font2)
		self.ecupnl.SetFont(font1)
		self.modelbox.AddSpacer(5)
		self.modelbox.Add(self.modell, 0, wx.CENTER)
		self.modelbox.Add(self.ecupnl, 0, wx.CENTER)
		self.modelbox.AddSpacer(5)
		self.modelp.SetSizer(self.modelbox)

		self.outersizer = wx.BoxSizer(wx.VERTICAL)
		self.outersizer.Add(self.adapterboxp, 0, wx.EXPAND | wx.ALL, 5)
		self.outersizer.Add(self.modelp, 0, wx.EXPAND | wx.ALL, 5)
		self.outersizer.Add(self.labelbook, 2, wx.EXPAND | wx.ALL, 5)
		self.outerp.SetSizer(self.outersizer)

		self.mainsizer = wx.BoxSizer(wx.VERTICAL)
		self.mainsizer.Add(self.outerp, 1, wx.EXPAND)
		self.mainsizer.SetSizeHints(self)
		self.SetSizer(self.mainsizer)

		self.securebutton.Bind(wx.EVT_BUTTON, self.OnSecure)
		self.adapterlist.Bind(wx.EVT_CHOICE, self.OnAdapterSelected)
		self.Bind(wx.EVT_CLOSE, self.OnClose)

		self.debuglog = HondaECU_LogPanel(self)

		dispatcher.connect(self.USBMonitorHandler, signal="USBMonitor", sender=dispatcher.Any)
		dispatcher.connect(self.AppPanelHandler, signal="AppPanel", sender=dispatcher.Any)
		dispatcher.connect(self.KlineWorkerHandler, signal="KlineWorker", sender=dispatcher.Any)

		self.usbmonitor = USBMonitor(self)
		self.klineworker = KlineWorker(self)

		self.Layout()
		self.Center()
		self.Show()

		self.usbmonitor.start()
		self.klineworker.start()

		self.settings = SettingsDialog(self)
		self.passwordd = PasswordDialog(self)

	def __clear_data(self):
		self.ecuinfo = {}

	def __clear_widgets(self):
		self.ecmidl.SetLabel("")
		self.flashcountl.SetLabel("")
		self.dtccountl.SetLabel("")
		self.modell.SetLabel("")
		self.ecupnl.SetLabel("")
		self.statusicon.SetBitmap(self.statusicons[0])
		self.statusbar.OnSize(None)

	def KlineWorkerHandler(self, info, value):
		if info in ["ecmid","flashcount","dtc","dtccount","state"]:
			self.ecuinfo[info] = value
			if info == "state":
				self.securebutton.Enable(False)
				self.statusicon.SetToolTip(wx.ToolTip("state: %s" % (str(value).split(".")[-1])))
				if value in [ECUSTATE.OFF,ECUSTATE.UNKNOWN]: #BLACK
					self.__clear_widgets()
					# self.statusicon.SetBitmap(self.statusicons[0])
				elif value in [ECUSTATE.RECOVER_NEW, ECUSTATE.RECOVER_OLD]: #YELLOW
					self.statusicon.SetBitmap(self.statusicons[1])
				elif value in [ECUSTATE.OK]: #GREEN
					self.securebutton.Enable(True)
					self.statusicon.SetBitmap(self.statusicons[2])
				elif value in [ECUSTATE.FLASH]: #BLUE
					self.statusicon.SetBitmap(self.statusicons[3])
				elif value in [ECUSTATE.SECURE]: #PURPLE
					self.statusicon.SetBitmap(self.statusicons[4])
				# elif value in [ECUSTATE.POSTWRITEx00,ECUSTATE.POSTWRITEx12]: #RED
				# 	self.statusicon.SetBitmap(self.statusicons[5])
			elif info == "ecmid":
				if len(value) > 0:
					ecmid = " ".join(["%02x" % i for i in value])
					self.ecmidl.SetLabel("   ECM ID: %s" % ecmid)
					if value in ECM_IDs:
						model = "%s (%s)" % (ECM_IDs[value]["model"], ECM_IDs[value]["year"])
						pn = ECM_IDs[value]["pn"]
					else:
						model = "Unknown Model"
						pn = "-"
						for m in ECM_IDs.keys():
							if m[:3] == value[:3]:
								model = "%s (%s)" % (ECM_IDs[m]["model"], ECM_IDs[m]["year"])
								break
					self.modell.SetLabel(model)
					self.ecupnl.SetLabel(pn)
					self.Layout()
			elif info == "flashcount":
				if value >= 0:
					self.flashcountl.SetLabel("   Flash Count: %d" % value)
			elif info == "dtccount":
				if value >= 0:
					self.dtccountl.SetLabel("   DTC Count: %d" % value)
			self.statusbar.OnSize(None)
		elif info == "data":
			if not info in self.ecuinfo:
				self.ecuinfo[info] = {}
			self.ecuinfo[info][value[0]] = value[1:]

	def OnSecure(self, event):
		self.passwordd._Show()

	def OnSettings(self, event):
		self.settings.Show()

	def OnClose(self, event):
		with open(self.configfile, 'w') as configfile:
			self.config.write(configfile)
		self.run = False
		self.usbmonitor.join()
		self.klineworker.join()
		wx.Yield()
		for w in wx.GetTopLevelWindows():
			w.Destroy()

	def sigint_handler(self, sig, frame):
		wx.CallAfter(self.OnClose,None)

	def OnDetectMap(self, event):
		with wx.FileDialog(self, "Open ECU dump file", wildcard="ECU dump (*.bin)|*.bin", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
			if fileDialog.ShowModal() == wx.ID_CANCEL:
				return
			pathname = fileDialog.GetPath()
			ecupn = os.path.splitext(os.path.split(pathname)[-1])[0]
			for i in ECM_IDs.values():
				if ecupn == i["pn"] and "keihinaddr" in i:
					fbin = open(pathname, "rb")
					nbyts = os.path.getsize(pathname)
					byts = bytearray(fbin.read(nbyts))
					fbin.close()
					idadr = int(i["keihinaddr"],16)
					wx.MessageDialog(None, "Map ID: " + byts[idadr:(idadr+7)].decode("ascii"), "", wx.CENTRE|wx.STAY_ON_TOP).ShowModal()
					return
			wx.MessageDialog(None, "Map ID: unknown", "", wx.CENTRE|wx.STAY_ON_TOP).ShowModal()

	def OnBinChecksum(self, event):
		with wx.FileDialog(self, "Open ECU dump file", wildcard="ECU dump (*.bin)|*.bin", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
			if fileDialog.ShowModal() == wx.ID_CANCEL:
				return
			pathname = fileDialog.GetPath()
			fbin = open(pathname, "rb")
			nbyts = os.path.getsize(pathname)
			byts = bytearray(fbin.read(nbyts))
			fbin.close()
			wx.MessageDialog(None, "Checksum: %s" % ("good" if checksum8bitHonda(byts)==0 else "bad"), "", wx.CENTRE|wx.STAY_ON_TOP).ShowModal()
			return

	def OnDebug(self, event):
		self.debuglog.Show()

	def OnAppButtonClicked(self, event):
		b = event.GetEventObject()
		if not b.appid in self.appanels:
			enablestates = None
			if "enable" in self.apps[b.appid]:
				enablestates = self.apps[b.appid]["enable"]
			self.appanels[b.appid] = self.apps[b.appid]["panel"](self, b.appid, self.apps[b.appid], enablestates)
			self.appbuttons[b.appid].Disable()
		self.appanels[b.appid].Raise()

	def USBMonitorHandler(self, action, device, config):
		dirty = False
		if action == "error":
			if not device in self.warned:
				self.warned.append(device)
				if platform.system() == "Windows":
					wx.MessageDialog(None, "libusb error: make sure libusbk is installed", "", wx.CENTRE|wx.STAY_ON_TOP).ShowModal()
		elif action == "add":
			if not device in self.ftdi_devices:
				self.ftdi_devices[device] = config
				dirty = True
		elif action =="remove":
			if device in self.ftdi_devices:
				if device == self.active_ftdi_device:
					dispatcher.send(signal="FTDIDevice", sender=self, action="deactivate", device=self.active_ftdi_device, config=self.ftdi_devices[self.active_ftdi_device])
					self.active_ftdi_device = None
					self.__clear_data()
				del self.ftdi_devices[device]
				dirty = True
		if len(self.ftdi_devices) > 0:
			if not self.active_ftdi_device:
				self.active_ftdi_device = list(self.ftdi_devices.keys())[0]
				dispatcher.send(signal="FTDIDevice", sender=self, action="activate", device=self.active_ftdi_device, config=self.ftdi_devices[self.active_ftdi_device])
				dirty = True
		else:
				pass
		if dirty:
			self.adapterlist.Clear()
			for device in self.ftdi_devices:
				cfg = self.ftdi_devices[device]
				self.adapterlist.Append("Bus %03d Device %03d: %s %s %s" % (cfg.bus, cfg.address, usb.util.get_string(cfg,cfg.iManufacturer), usb.util.get_string(cfg,cfg.iProduct), usb.util.get_string(cfg,cfg.iSerialNumber)))
			if self.active_ftdi_device:
				self.adapterlist.SetSelection(list(self.ftdi_devices.keys()).index(self.active_ftdi_device))


	def OnAdapterSelected(self, event):
		device = list(self.ftdi_devices.keys())[self.adapterlist.GetSelection()]
		if device != self.active_ftdi_device:
			if self.active_ftdi_device != None:
				dispatcher.send(signal="FTDIDevice", sender=self, action="deactivate", device=self.active_ftdi_device, config=self.ftdi_devices[self.active_ftdi_device])
			self.__clear_data()
			self.active_ftdi_device = device
			dispatcher.send(signal="FTDIDevice", sender=self, action="activate", device=self.active_ftdi_device, config=self.ftdi_devices[self.active_ftdi_device])

	def AppPanelHandler(self, appid, action):
		if action == "close":
			if appid in self.appanels:
				del self.appanels[appid]
				self.appbuttons[appid].Enable()
