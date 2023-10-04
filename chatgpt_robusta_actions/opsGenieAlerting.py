# Base needed imports

# Internal resources
from .exceptions import *

# External resources
import json
import time
import os
import opsgenie_sdk
import pytz
from datetime import datetime
import tempfile
import logging
from logging import Logger

VERSION = "1.3.0"

class OpsGenieAlerting(object):
    def __init__(self, host, opsgenie_api_key, team_name, activationState = False, request_timeout = 10, logger: Logger = None):
        if logger is None:
            self.logger = Logger("alfabet_root")
            self.logger.disabled = True
            self.logger.propagate = False
        else:
            self.logger = logging.getLogger(logger.name) 
        self.logger.debug(f"Instantiate module object of class '{self.__class__.__module__ + '.' + self.__class__.__qualname__}' and version '{VERSION}'")

        self.conf = opsgenie_sdk.configuration.Configuration()
        self.conf.api_key['Authorization'] = opsgenie_api_key
        self.conf.host = host

        self.api_client = opsgenie_sdk.api_client.ApiClient(configuration=self.conf)
        self.alert_api = opsgenie_sdk.AlertApi(api_client=self.api_client)
        self.request_timeout = request_timeout

        self.team_name = team_name

        self.activationState = activationState

    def createAlert(self, exceptionSubject: str, exceptionMessage: str, alias: str, alertAttributes , priority: str = "P5", tags = [], attachmentDetails: str = None):        
        result = False
        if self.activationState:
            self.logger.warning(f"OpsGenie alerting has been disabled in the configuration! Fake OpsGenie alert triggered for '{exceptionSubject}'!")
            return

        self.logger.debug(f"Creating OpsGenie alert for '{exceptionSubject}'...")
        body = opsgenie_sdk.CreateAlertPayload(
            message = f"{exceptionSubject}",
            alias=alias,
            description=exceptionMessage,
            responders=[{
                'name': self.team_name,
                'type': 'team'
            }],
            visible_to=[
            {'name': self.team_name,
            'type': 'team'}],
            #actions=['FixBackup', 'Please open a ticket'],
            tags=tags,
            details=alertAttributes,
            priority=priority
        )
        try:
            create_response = None
            try:
                create_request = self.alert_api.create_alert(create_alert_payload=body, _request_timeout=self.request_timeout)
                self.logger.debug(f"Sent request to create an OpsGenie alert: '{create_request.result}' with id '{create_request.request_id}'!")
                create_response = self.__waitForOpsgenieOperationSuccessResponse(create_request)
                self.logger.info("Successfully created OpsGenie alert!")
                result = True
            except ResponseCheckRetryError as ex:
                self.logger.error(f"Unable to create OpsGenie alert '{create_request}'!")

            if attachmentDetails is not None and create_response is not None:
                # Upload stack trace as attachment
                attachmentName = f"BackupCheckStackTrace_{alias}_{datetime.now(tz=pytz.utc).strftime('%Y-%m-%d-%H:%M:%S-%Z')}_"
                tmpFile = tempfile.NamedTemporaryFile(prefix=attachmentName, suffix='.txt')
                try:
                    tmpFile.write(str.encode(attachmentDetails))
                    tmpFile.flush()
                    try:
                        add_response = self.alert_api.add_attachment(identifier=create_response.data.alert_id, file=tmpFile.name)
                        if add_response.result == "Request will be processed":
                            self.__waitForOpsgenieOperationSuccessResponse(add_response)
                        else:
                            self.logger.debug(f"{add_response.result}")
                    except ResponseCheckRetryError as ex:
                        self.logger.error(f"Unable to add attachment to OpsGenie alert!")
                        result = False
                except opsgenie_sdk.ApiException as err:
                    self.logger.exception(f"Exception when calling AlertApi->add attachment: {err}", stack_info=1)
                    result = False
                
                tmpFile.close()

        except opsgenie_sdk.ApiException as ex:
            self.logger.exception(ex)
            raise Exception("Unable to create OpsGenie alert!", ex)

        return result

    def __waitForOpsgenieOperationSuccessResponse(self, requestResponse):
        counter = 0
        self.logger.debug(f"Waiting for operation '{requestResponse.request_id}' - '{requestResponse.url}' to complete...")
        while True:
            time.sleep(1)
            if counter >= 15:
                self.logger.error(f"Unable to process operation for: '{requestResponse.request_id}' - '{requestResponse.url}'. Max retries reached!")
                raise ResponseCheckRetryError(f"Unable to process operation for: '{requestResponse.request_id}' - '{requestResponse.url}'", 15)
            try:
                request_response = self.alert_api.get_request_status(request_id=requestResponse.request_id)
                if request_response.data.is_success:
                    if counter >= 1:
                        self.logger.info(f"After multiple iterations the operation '{requestResponse.request_id}' - '{requestResponse.url}' was processed with status '{request_response.data.status}'!")
                    else:
                        self.logger.debug(f"Operation '{requestResponse.request_id}' - '{requestResponse.url}' was processed with status '{request_response.data.status}'!")
                    return request_response
            except opsgenie_sdk.ApiException as e:
                try:
                    self.logger.warning(f"{json.loads(e.body)['message']}")
                except Exception:
                    self.logger.warning(f"Unable to get request response: {e}")
            except Exception as ex:
                self.logger.exception(ex)
            counter += 1

    def getOpenAlertsByTagsAndContainingMessage(self, tags = [], containingMessage: str = "", additionalQuery: str = ""):
        tagsForQuery = ""
        for tag in tags: tagsForQuery += f"tag: '{tag}' "
        query = f"status:'open' {tagsForQuery} message: '{containingMessage}'"

        return self.getAlertsByQuery(f"{additionalQuery} {query}")
    
    def getOpenAlertsByTagsAndContainingDescription(self, tags = [], containingDescription: str = "", additionalQuery: str = ""):
        tagsForQuery = ""
        for tag in tags: tagsForQuery += f"tag: '{tag}' "
        query = f"status:'open' {tagsForQuery} description: '{containingDescription}'"

        return self.getAlertsByQuery(f"{additionalQuery} {query}")

    def getAlertsByQuery(self, query):
        self.logger.debug(f"Looking up alerts with query \"{query}\"...")
        try:
            api_response = self.alert_api.list_alerts(query=query)
            self.logger.debug(f"Returning {len(api_response.data)} alert/s from query \"{query}\"!")
            return api_response.data
        except opsgenie_sdk.ApiException as err:
            self.logger.exception(f"Exception when calling AlertApi->list_alerts: {err}", stack_info=1)

    def acknowledgeAlert(self, alert, note: str, createSource: str, createUser: str = "OpsGenie service token"):
        if alert.acknowledged:
            self.logger.info(f"Alert is already acknowledged and will not be processed!")
            return True
        
        self.logger.debug(f"Acknowledging alert '{alert.id}'...")
        try:
            try:
                ack_alert_payload = opsgenie_sdk.AcknowledgeAlertPayload(user=createUser, note=note, source=createSource)
                api_response = self.alert_api.acknowledge_alert(alert.id, acknowledge_alert_payload = ack_alert_payload)
                self.__waitForOpsgenieOperationSuccessResponse(api_response)
                self.logger.info(f"Alert '{alert.id}' was successfully acknowledged!")
                return True
            except ResponseCheckRetryError as ex:
                self.logger.error(f"Unable to acknowledge OpsGenie alert!")
        except opsgenie_sdk.ApiException as err:
            self.logger.exception(f"Exception when calling AlertApi->acknowledge_alert: {err}", stack_info=1)
        return False

    def addNoteToAlert(self, alert, note: str, createSource: str, createUser: str = "OpsGenie service token"):
        self.logger.debug(f"Adding note to alert '{alert.id}'...")
        try:
            try:
                add_note_to_alert_payload = opsgenie_sdk.AddNoteToAlertPayload(user=createUser, note=note, source=createSource)
                api_response = self.alert_api.add_note(alert.id, add_note_to_alert_payload)
                self.__waitForOpsgenieOperationSuccessResponse(api_response)
                self.logger.info(f"Note was successfully added to alert '{alert.id}'!")
                return True
            except ResponseCheckRetryError as ex:
                self.logger.error(f"Unable to add note to OpsGenie alert!")
        except opsgenie_sdk.ApiException as err:
            self.logger.exception(f"Exception when calling AlertApi->add_note: {err}", stack_info=1)
        return False
    
    def addTagsToAlert(self, alert, tags, createSource: str, createUser: str = "OpsGenie service token"):
        self.logger.debug(f"Adding tag/s to alert '{alert.id}'...")
        try:
            try:
                add_tags_to_alert_payload = opsgenie_sdk.AddTagsToAlertPayload(user=createUser, tags=tags, source=createSource) 
                api_response = self.alert_api.add_tags(alert.id, add_tags_to_alert_payload)
                self.__waitForOpsgenieOperationSuccessResponse(api_response)
                self.logger.info(f"Tag/s was/were successfully added to alert '{alert.id}'!")
                return True
            except ResponseCheckRetryError as ex:
                self.logger.error(f"Unable to add tag/s to OpsGenie alert!")
        except opsgenie_sdk.ApiException as err:
            self.logger.exception(f"Exception when calling AlertApi->add_tags: {err}", stack_info=1)
        return False

    def closeAlert(self, alert, reason: str, reasonSource: str, reasonUser: str = "OpsGenie service token", setCloseTags = []):
        self.logger.debug(f"Closing alert '{alert.alias}' because '{reason}' ...")
        try:
            try:
                close_alert_payload = opsgenie_sdk.CloseAlertPayload(user=reasonUser, note=reason, source=reasonSource)
                api_response = self.alert_api.close_alert(alert.id, close_alert_payload=close_alert_payload)
                self.__waitForOpsgenieOperationSuccessResponse(api_response)
                self.logger.info(f"Alert '{alert.id}' was successfully closed!")
                if len(setCloseTags) > 0:
                    self.addTagsToAlert(alert, setCloseTags, reasonSource, reasonUser)
                return True
            except ResponseCheckRetryError as ex:
                self.logger.error(f"Unable to close OpsGenie alert '{alert.id}'!")
        except opsgenie_sdk.ApiException as err:
            self.logger.exception(f"Exception when calling AlertApi->close_alert: {err}", stack_info=1)
        return False

    def closeUnacknowledgedAlert(self, alert, reason: str, reasonSource: str, reasonUser: str = "OpsGenie service token", setCloseTags = []):
        self.logger.debug(f"Alert '{alert.id}' is set to be closed because '{reason}' ...")
        
        if alert.acknowledged:
            self.logger.debug(f"Alert is acknowledged and will not be closed automatically! A note was added only!")
            self.addNoteToAlert(alert, f"This alert was resolved and can be closed because '{reason}' !{os.linesep}{os.linesep}Note:{os.linesep}Auto-close for this alert is disabled because the alert is acknowledged!", reasonSource, reasonUser)
            return False
        else:
            return self.closeAlert(alert, reason, reasonSource, reasonUser, setCloseTags)
    
    def updateAlertPriority(self, alert, newPriority: str):
        self.logger.debug(f"Updating priority for alert '{alert.alias}' with new priority '{newPriority}' ...")
        try:
            try:
                updateAlertPriorityPayload = opsgenie_sdk.UpdateAlertPriorityPayload(newPriority)
                api_response = self.alert_api.update_alert_priority(alert.id, update_alert_priority_payload=updateAlertPriorityPayload)
                self.__waitForOpsgenieOperationSuccessResponse(api_response)
                self.logger.info(f"Priority for alert '{alert.id}' was successfully updated!")
                return True
            except ResponseCheckRetryError as ex:
                self.logger.error(f"Unable to update OpsGenie alert priority for alert '{alert.id}'!")
        except opsgenie_sdk.ApiException as err:
            self.logger.exception(f"Exception when calling AlertApi->update_alert_priority: {err}", stack_info=1)
        return False

    def getAlert(self, identifier: str, identifierType: str = "alias"):
        self.logger.debug(f"Looking up alert with identifier '{identifier}'...")
        try:
            api_response = self.alert_api.get_alert(identifier=identifier, identifier_type=identifierType)
            self.logger.debug(f"Returning alert '{api_response.data.id}'!")
            return api_response.data
        except opsgenie_sdk.ApiException as err:
            self.logger.exception(f"Exception when calling AlertApi->get_alert: {err}", stack_info=1)

    def updateAlertDetails(self, alert, newDetails: dict):
        self.logger.debug(f"Updating details for alert '{alert.alias} ...")
        try:
            try:
                updateAlertDetailsPayload = opsgenie_sdk.AddDetailsToAlertPayload(details=newDetails)
                api_response = self.alert_api.add_details(alert.id, updateAlertDetailsPayload, identifier_type="id")
                self.__waitForOpsgenieOperationSuccessResponse(api_response)
                self.logger.info(f"Details for alert '{alert.id}' were successfully updated!")
                return True
            except ResponseCheckRetryError as ex:
                self.logger.error(f"Unable to update OpsGenie alert details for alert '{alert.id}'!")
        except opsgenie_sdk.ApiException as err:
            self.logger.exception(f"Exception when calling AlertApi->add_details: {err}", stack_info=1)
        return False

    def assignAlert(self, alert, newOwner: str):
        self.logger.debug(f"Updating assignee for alert '{alert.alias} ...")
        try:
            try:
                userRecipient = opsgenie_sdk.UserRecipient(username=newOwner)
                assignAlertPayload = opsgenie_sdk.AssignAlertPayload(owner=userRecipient)
                api_response = self.alert_api.assign_alert(alert.id, assignAlertPayload, identifier_type="id")
                self.__waitForOpsgenieOperationSuccessResponse(api_response)
                self.logger.info(f"Assignee for alert '{alert.id}' were successfully updated!")
                return True
            except ResponseCheckRetryError as ex:
                self.logger.error(f"Unable to update OpsGenie alert assignee for alert '{alert.id}'!")
        except opsgenie_sdk.ApiException as err:
            self.logger.exception(f"Exception when calling AlertApi->add_details: {err}", stack_info=1)
        return False