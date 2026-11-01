from django.test import TestCase
from django.test import Client
from main_app.models import *
import json
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from time import sleep

def setup_fixtures(self):
    self.user = User.objects.create_user('user', 'em@a.il', 'password')
    self.user.save()

    self.apparatus_type = ApparatusType(
        name = 'TestExperiment',
        description = 'X',
        scientific_area = 'X',
        lab_type = 'X'
    )
    self.apparatus_type.save()

    self.apparatus = Apparatus(
        apparatus_type = self.apparatus_type,
        location = 'Prague',
        secret = 'secret_code',
        owner = 'Somebody',
        timeout = 1,
    )
    self.apparatus.save()
    
    Apparatus(
        apparatus_type = self.apparatus_type,
        location = 'Dummy',
        secret = 'no',
        owner = 'Nobody',
        timeout = 1,
    ).save()

    self.basic_protocol = Protocol(
        apparatus_type = self.apparatus_type,
        name = 'Basic protocol',
        config = {"type": "object"}
    )
    self.basic_protocol.save()

    self.protocol_with_schema = Protocol(
        apparatus_type = self.apparatus_type,
        name = 'Test',
        config = {"type": "object", "properties": {"displacement": {"type": "number", "description": "displacement", "minimum": 5, "maximum": 20, "multipleOf": 0.1}, "enumerator": {"type": "string", "enum": ["A", "B"]}}, "required": ["displacement", "enumerator"]}
    )
    self.protocol_with_schema.save()

    self.apparatus.protocols.add(self.protocol_with_schema)
    self.apparatus.protocols.add(self.basic_protocol)
    self.apparatus.save()

    self.client = Client()
    login_result = self.client.login(username='user', password='password')
    self.assertEqual(login_result, True)


class ExecutionAPI(TestCase):
    def setUp(self):
        setup_fixtures(self)
        
    def test_apparatus_list(self):
        response = self.client.get('/api/v1/apparatus')
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(len(response), 2)

    def test_configure_execution_success(self):
        response = self.client.post('/api/v1/execution', {
            'apparatus': self.apparatus.pk, 
            'protocol': self.basic_protocol.pk, 
            'config': {}}
        )
        self.assertEqual(response.status_code, 201)
        response = json.loads(response.content)

        execution = Execution.objects.get(pk=response["id"])
        self.assertEqual(execution.status, 'C')
        self.assertEqual(execution.user, self.user)
        self.assertEqual(execution.apparatus, self.apparatus)

    def test_configure_execution_foreign_key_fail(self):
        """Ensures that the FKs are validated"""
        response = self.client.post('/api/v1/execution', {
            'apparatus': 999, 
            'protocol': self.basic_protocol.pk, 
            'config': {}}
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post('/api/v1/execution', {
            'apparatus': self.apparatus, 
            'protocol': 999, 
            'config': {}}
        )
        self.assertEqual(response.status_code, 400) 

    def test_execution_flow(self):
        
        # Wait until timeout from configs expires
        sleep(2)
        # Check the queue before any execution is there
        response = self.client.get('/api/v1/apparatus/' + str(self.apparatus.pk) + '/nextexecution',
        HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 200)
        # This should still work
        self.assertEqual('Online', Apparatus.objects.get(pk=self.apparatus.pk).current_status)
        
        # Configure an execution
        response = self.client.post('/api/v1/execution', {
            'apparatus': self.apparatus.pk, 
            'protocol': self.basic_protocol.pk, 
            'config': {}}
        )
        self.assertEqual(response.status_code, 201)
        response = json.loads(response.content)
        execution_id = response["id"]

        # Check if status = C
        response = self.client.get('/api/v1/execution/' + str(execution_id))
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(response["status"], 'C')

        time_before_start = timezone.now()

        # Enqueue execution
        response = self.client.put('/api/v1/execution/' + str(execution_id) + '/start')
        self.assertEqual(response.status_code, 200)

        # Check if status is R in database
        execution = Execution.objects.get(pk=execution_id)
        self.assertEqual(execution.status, 'Q')
        #self.assertLess(execution.start - time_before_start, 3)

        # Check that it cannot be run again
        response = self.client.put('/api/v1/execution/' + str(execution_id) + '/start')
        self.assertEqual(response.status_code, 400)

        # Check that we fail on non-existing execution id
        response = self.client.put('/api/v1/execution/999/start')
        self.assertEqual(response.status_code, 404)

        response = self.client.get('/api/v1/execution/' + str(execution_id))
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(response["status"], 'Q')

        response = self.client.get('/api/v1/execution/999/status')
        self.assertEqual(response.status_code, 404)

        response = self.client.post('/api/v1/execution', {
            'apparatus': self.apparatus.pk, 
            'protocol': self.basic_protocol.pk, 
            'config': {}}
        )
        self.assertEqual(response.status_code, 201)
        response = json.loads(response.content)
        next_execution_id = response["id"]

        
        response = self.client.get('/api/v1/apparatus/' + str(self.apparatus.pk) + '/nextexecution',
        HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(response["id"], execution_id)
        self.assertEqual(response["status"], "Q")
        self.assertEqual('Online', Apparatus.objects.get(pk=self.apparatus.pk).current_status)
        sleep(0.5)
        self.assertEqual('Online', Apparatus.objects.get(pk=self.apparatus.pk).current_status)
        sleep(2)
        self.assertEqual('Offline', Apparatus.objects.get(pk=self.apparatus.pk).current_status)
        
        response = self.client.put('/api/v1/apparatus/' + str(self.apparatus.pk) + '/heartbeat', 
        HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 200)

        
        
        request_time = timezone.now()
        response = self.client.put('/api/v1/execution/' + str(execution_id) + '/status', {
            'status': 'R'
        }, content_type='application/json', HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 200)
        response = self.client.get('/api/v1/execution/' + str(execution_id))
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertLess((parse_datetime(response["start"])-request_time).total_seconds(),1)

        response = self.client.get('/api/v1/apparatus/999/nextexecution')
        self.assertEqual(response.status_code, 404)    

        # Cannot change status to invalid
        response = self.client.put('/api/v1/execution/' + str(execution_id) + '/status', {
            "status": "C"
        }, content_type='application/json', HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 400)

        # RESULT NO AUTH
        response = self.client.post('/api/v1/result', {
            'execution': execution_id,
            'value': json.dumps({'g': 9.81}),
            'result_type': 'p',
        })
        self.assertEqual(response.status_code, 403)


        response = self.client.post('/api/v1/result', {
            'execution': execution_id,
            'value': json.dumps({'g': 9.81}),
            'result_type': 'p',
        },HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 201)
        response = json.loads(response.content)
        partial_result_id = response['id']
        partial_result = Result.objects.get(pk=partial_result_id)
        self.assertEqual(partial_result.result_type, 'p')

        # Allow adding multiple partial results:
        response = self.client.post('/api/v1/result', {
            'execution': execution_id,
            'value': json.dumps({'g': 9.815}),
            'result_type': 'p',
        },HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 201)

        response = self.client.get('/api/v1/execution/' + str(execution_id) + '/result')
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(len(response), 0)
        
        response = self.client.get('/api/v1/execution/' + str(execution_id) + '/result/0')
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(len(response), 2)
        
        # Add one marker result
        response = self.client.post('/api/v1/result', {
            'execution': execution_id,
            'value': json.dumps({'g': 9.815}),
            'result_type': 'p',
        },HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 201)
        response = json.loads(response.content)
        partial_result_id = response['id']
        
        for i in range(9):
            self.client.post('/api/v1/result', {
                'execution': execution_id,
                'value': json.dumps({'g': 9.815}),
                'result_type': 'p',
                },HTTP_AUTHENTICATION = 'secret_code')  
            
        response = self.client.get('/api/v1/execution/' + str(execution_id) + '/result/' + str(partial_result_id))
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(len(response), 10)
        
        response = self.client.get('/api/v1/execution/' + str(execution_id) + '/result/' + str(partial_result_id) + '/5')
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(len(response), 5)
        
        request_time = timezone.now()
        response = self.client.post('/api/v1/result', { 
            'execution': execution_id,
            'value': json.dumps({'g': 9.82}),
            'result_type':'f',
        }, HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 201)
        response = json.loads(response.content)
        final_result_id = response['id']
        final_result = Result.objects.get(pk=final_result_id)
        self.assertEqual(final_result.result_type, 'f')
        # Execution state changed to Finished
        
        execution = Execution.objects.get(pk=execution_id)
        self.assertEqual(execution.status, 'F')
        self.assertLess((execution.end - request_time).total_seconds(), 1)

        # NOT allow multiple final results
        response = self.client.post('/api/v1/result', { 
            'execution': execution_id,
            'value': json.dumps({'g': 9.82}),
            'result_type':'f',
        },HTTP_AUTHENTICATION = 'secret_code')
        self.assertEqual(response.status_code, 400)

        # TEST INVALID SCHEMA
        response = self.client.post('/api/v1/execution', {
            'apparatus': self.apparatus.pk, 
            'protocol': self.protocol_with_schema.pk, 
            'config': {'a':'b'}}
        )
        self.assertEqual(response.status_code, 400)

        # TEST MultipleOf validation
        response = self.client.post('/api/v1/execution', {
            'apparatus': self.apparatus.pk, 
            'protocol': self.protocol_with_schema.pk, 
            'config': {'displacement': 5.6, 'enumerator':'A'} }
        , content_type='application/json')
        self.assertEqual(response.status_code, 201)
        response = json.loads(response.content)
        new_exec_id = response['id']

        # TEST VALID SCHEMA
        response = self.client.post('/api/v1/execution', {
            'apparatus': self.apparatus.pk, 
            'protocol': self.protocol_with_schema.pk, 
            'config': {'displacement': 6, 'enumerator':'A'} }
        , content_type='application/json')
        self.assertEqual(response.status_code, 201)
        response = json.loads(response.content)
        new_exec_id = response['id']

        # TEST UPDATE
        response = self.client.put('/api/v1/execution/' + str(new_exec_id), {
            'apparatus': self.apparatus.pk, 
            'protocol': self.protocol_with_schema.pk, 
            'config': {'displacement': 7, 'enumerator':'A'} }
        , content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        response = self.client.put('/api/v1/execution/' + str(new_exec_id) + '/name', {
            'name': 'testname',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        self.assertEqual('testname', Execution.objects.get(pk=new_exec_id).name)

        # UPDATE WITH INVALID SCHEMA
        response = self.client.put('/api/v1/execution/' + str(new_exec_id), {
            'apparatus': self.apparatus.pk, 
            'protocol': self.protocol_with_schema.pk, 
            'config': {'displacement': 2, 'enumerator':'A'} }
        , content_type='application/json')
        self.assertEqual(response.status_code, 400)

        # INVALID SCHEMA AGAIN
        response = self.client.post('/api/v1/execution', {
            'apparatus': self.apparatus.pk, 
            'protocol': self.protocol_with_schema.pk, 
            'config': {'displacement': 4, 'enumerator':'A'} }
        , content_type='application/json')
        self.assertEqual(response.status_code, 400)

        # Read all three written results
        response = self.client.get('/api/v1/execution/' + str(execution_id) + '/result')
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(len(response), 1)
        
        response = self.client.get('/api/v1/execution/' + str(execution_id) + '/result/0')
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(len(response), 3)
        second_id = response[1]['id']

        # Read part of results
        response = self.client.get('/api/v1/execution/' + str(execution_id) + '/result/' + str(second_id))
        response = json.loads(response.content)
        self.assertEqual(len(response), 2)

        # Check 404
        response = self.client.get('/api/v1/execution/' + str(execution_id) + '/result/154')
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(len(response), 0)
        

        



