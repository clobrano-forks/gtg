# -*- coding: utf-8 -*-
# Copyright (c) 2009 - Luca Invernizzi <invernizzi.l@gmail.com>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
from time import sleep
#import subprocess
import gobject
from xdg.BaseDirectory import xdg_cache_home
#import pickle
from GTG import _

# IMPORTANT This adds the plugin path to python sys path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))+'/pyrtm')
from gtg_proxy import GtgProxy
from rtm_proxy import RtmProxy
from utility import smartSaveToFile, smartLoadFromFile, filterAttr, unziplist
import rtm


class SyncEngine (object):

    def __init__(self, this_plugin):
        super(SyncEngine, self).__init__()
        self.this_plugin = this_plugin
        self.logger = self.this_plugin.plugin_api.get_logger()
        self.rtm_proxy = RtmProxy(self.logger)
        self.gtg_proxy = GtgProxy(self.this_plugin.plugin_api,\
                                 self.logger)
        self.rtm_has_logon = False

    def rtmLogin(self):
        self.rtm_has_logon = self.rtm_proxy.login()

    def rtmHasLogon(self):
        return self.rtm_has_logon

    def _firstSynchronization(self):
        gtg_to_rtm_id_mapping = []
        #generating sets to perform intersection of tasks
        #NOTE: assuming different titles!
        gtg_task_titles_set = set(map(lambda x: x.title, self.gtg_list))
        rtm_task_titles_set = set(map(lambda x: x.title, self.rtm_list))
        #tasks in common
        for title in rtm_task_titles_set.intersection(gtg_task_titles_set):
            gtg_to_rtm_id_mapping.append(
                   (filterAttr(self.gtg_list, 'title', title)[0].id,
                     filterAttr(self.rtm_list, 'title', title)[0].id))

        #tasks that must be added to GTG
        rtm_added = rtm_task_titles_set.difference(gtg_task_titles_set)
        if len(rtm_added) > 0:
            self.update_status(_("Adding tasks to gtg.."))
            self.update_progressbar(0.4)
        for title in rtm_added:
            self.update_substatus(_("Adding ") + title)
            base_task = filterAttr(self.rtm_list, 'title', title)[0]
            new_task = self.gtg_proxy.newTask(title, True)
            new_task.copy(base_task)
            gtg_to_rtm_id_mapping.append((new_task.id, base_task.id))

        #tasks that must be added to RTM
        gtg_added = gtg_task_titles_set.difference(rtm_task_titles_set)
        if len(gtg_added) > 0:
            self.update_status(_("Adding tasks to rtm.."))
            self.update_progressbar(0.5)
        for title in gtg_added:
            self.update_substatus(_("Adding ") + title)
            base_task = filterAttr(self.gtg_list, 'title', title)[0]
            new_task = self.rtm_proxy.newTask(title)
            new_task.copy(base_task)
            gtg_to_rtm_id_mapping.append((base_task.id, new_task.id))
        return gtg_to_rtm_id_mapping

    def synchronize(self):
        try:
            self.synchronizeWorker()
        except rtm.RTMAPIError, exception:
            self.__log(str(exception))
            self.close_gui(str(exception))
        except rtm.RTMError, exception:
            self.__log(str(exception))
            self.close_gui(str(exception))
        except Exception, exception:
            self.__log(str(exception))
            self.close_gui(_("Synchronization failed."))

    def synchronizeWorker(self):
        self.update_status(_("Downloading task list..."))
        self.update_progressbar(0.1)
        self.__log("RTM sync started!")
        self.gtg_proxy.generateTaskList()
        self.rtm_proxy.generateTaskList()

        self.update_status(_("Analyzing tasks..."))
        self.update_progressbar(0.2)
        self.gtg_list = self.gtg_proxy.task_list
        self.rtm_list = self.rtm_proxy.task_list

        ## loading the mapping of the last sync
        cache_dir = os.path.join(xdg_cache_home, 'gtg/plugins/rtm-sync')
        gtg_to_rtm_id_mapping = smartLoadFromFile(\
                               cache_dir, 'gtg_to_rtm_id_mapping')
        if gtg_to_rtm_id_mapping is None:
            ###this is the first synchronization
            self.update_status(_("Running first synchronization..."))
            self.update_progressbar(0.3)
            gtg_to_rtm_id_mapping = \
                    self._firstSynchronization()
        else:
            ###this is an update
            self.update_status(_("Analyzing last sync..."))
            self.update_progressbar(0.3)
            gtg_id_current_set = set(map(lambda x: x.id, self.gtg_list))
            rtm_id_current_set = set(map(lambda x: x.id, self.rtm_list))
            if len(gtg_to_rtm_id_mapping)>0:
                gtg_id_previous_list, rtm_id_previous_list = \
                        unziplist(gtg_to_rtm_id_mapping)
            else:
                gtg_id_previous_list, rtm_id_previous_list=[], []
            gtg_id_previous_set = set(gtg_id_previous_list)
            rtm_id_previous_set = set(rtm_id_previous_list)
            gtg_to_rtm_id_dict = dict(gtg_to_rtm_id_mapping)
            rtm_to_gtg_id_dict = dict(zip(rtm_id_previous_list, \
                                          gtg_id_previous_list))

            #We'll generate a new mapping between gtg and rtm task ids
            gtg_to_rtm_id_mapping = []

            #tasks removed from gtg since last synchronization
            gtg_removed = gtg_id_previous_set.difference(gtg_id_current_set)
            #tasks removed from rtm since last synchronization
            rtm_removed = rtm_id_previous_set.difference(rtm_id_current_set)
            #tasks added to gtg since last synchronization
            gtg_added = gtg_id_current_set.difference(gtg_id_previous_set)
            #tasks added to rtm since last synchronization
            rtm_added = rtm_id_current_set.difference(rtm_id_previous_set)
            #tasks still in common(which may need to be updated)
            gtg_common = gtg_id_current_set.difference(gtg_added)\
                    .difference(gtg_removed)

            #Delete from rtm the tasks that have been removed in gtg
            if len(gtg_removed) > 0:
                self.update_status(_("Deleting tasks from rtm.."))
                self.update_progressbar(0.4)
            for gtg_id in gtg_removed:
                rtm_id = gtg_to_rtm_id_dict[gtg_id]
                rtm_task = filterAttr(self.rtm_list, 'id', rtm_id)
                self.__log("deleting from rtm task" + str(rtm_id))
                rtm_task = self.__to_list(rtm_task)
                if len(rtm_task) != 0:
                    self.update_substatus(_("Deleting ") + rtm_task[0].title)
                    map(lambda task: task.delete(), rtm_task)

            #Delete from gtg the tasks that have been removed in rtm
            if len(rtm_removed) > 0:
                self.update_status(_("Deleting tasks from gtg.."))
                self.update_progressbar(0.5)
            for rtm_id in rtm_removed:
                gtg_id = rtm_to_gtg_id_dict[rtm_id]
                gtg_task = filterAttr(self.gtg_list, 'id', gtg_id)
                gtg_task = self.__to_list(gtg_task)
                if len(gtg_task) != 0:
                    self.update_substatus(_("Deleting ") + gtg_task[0].title)
                    gtg_task = self.__to_list(gtg_task)
                    map(lambda task: task.delete(), gtg_task)
                    gtg_common.discard(gtg_id)

            #tasks that must be added to RTM
            #NOTE: should we check if the title is already present in the
            #other back-end, to be more robust?(Idem for vice-versa)
            if len(gtg_added) >0:
                self.update_status(_("Adding tasks to rtm.."))
                self.update_progressbar(0.6)
            for gtg_id in gtg_added:
                gtg_task = filterAttr(self.gtg_list, 'id', gtg_id)[0]
                self.update_substatus(_("Adding ") + gtg_task.title)
                rtm_task = self.rtm_proxy.newTask(gtg_task.title)
                rtm_task.copy(gtg_task)
                gtg_to_rtm_id_mapping.append((gtg_id, rtm_task.id))

            #tasks that must be added to GTG
            if len(rtm_added) >0:
                self.update_status(_("Adding tasks to rtm.."))
                self.update_progressbar(0.7)
            for rtm_id in rtm_added:
                rtm_task = filterAttr(self.rtm_list, 'id', rtm_id)[0]
                self.update_substatus(_("Adding ") + rtm_task.title)
                gtg_task = self.gtg_proxy.newTask(rtm_task.title, True)
                gtg_task.copy(rtm_task)
                gtg_to_rtm_id_mapping.append((gtg_task.id, rtm_id))

            #tasks in common
            if len(gtg_common) >0:
                self.update_status(_("Updating remaining tasks.."))
                self.update_progressbar(0.8)
            for gtg_id in gtg_common:
                rtm_id = gtg_to_rtm_id_dict[gtg_id]
                gtg_task = filterAttr(self.gtg_list, 'id', gtg_id)[0]
                rtm_task = filterAttr(self.rtm_list, 'id', rtm_id)[0]
                self.__log("rtm_task.modified |" + str(rtm_task.modified))
                self.__log("gtg_task.modified |" + str(gtg_task.modified))
                #NOTE: rtm does not set the modified date on new tasks,
                #      so a comparison between the modified times is not
                #      always possible. However, here the task have been synced
                #      before, so gtg takes precedence ~~~~Invernizzi
                if rtm_task.modified == None or \
                    rtm_task.modified > gtg_task.modified:
                    self.update_substatus(_("Updating ") + rtm_task.title)
                    gtg_task.copy(rtm_task)
                else:
                    self.update_substatus(_("Updating ") + gtg_task.title)
                    rtm_task.copy(gtg_task)

                gtg_to_rtm_id_mapping.append((gtg_id, rtm_id))

        self.update_status(_("Saving current state.."))
        self.update_progressbar(0.9)

        smartSaveToFile(cache_dir, 'gtg_to_rtm_id_mapping',\
                        gtg_to_rtm_id_mapping)
        #TODO: ask if ok or undo(easy on rtm(see timeline),
        self.close_gui(_("Synchronization completed."))

    def close_gui(self, msg):
        self.update_status(msg)
        self.update_progressbar(1.0)
        sleep(2)
        self.update_status(_("Closing in one second"))
        sleep(1)
        gobject.idle_add(self.this_plugin.purgeDialog)

    def update_progressbar(self, percent):
        self.this_plugin.progressbar_percent = percent
        gobject.idle_add(self.this_plugin.set_progressbar)

    def update_status(self, status):
        self.__log(status)
        self.this_plugin.status = status
        gobject.idle_add(self.this_plugin.set_status)

    def update_substatus(self, substatus):
        self.__log(substatus)
        self.this_plugin.substatus = substatus
        gobject.idle_add(self.this_plugin.set_substatus)

    def __log(self, string):
        if self.logger:
            self.logger.debug(string)

    def __to_list(self, something):
        """If something is not a list, it just embeds it into a
           list."""
        #I'm sure there is some clever way to do that in python
        #  but, sadly, I don't know it. ~~~~Invernizzi
        if   isinstance(something, list):
            return something
        else:
            return [something]
