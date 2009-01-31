# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
import logging
import os
import wsgiref.handlers
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.api import memcache

template_path = os.path.join(os.path.dirname(__file__), 'templates')

# models

def transaction(method):
  def decorate(*args, **kwds):
    return db.run_in_transaction(method, *args, **kwds)
  return decorate

class Account(db.Model):
  name = db.StringProperty()
  created_at = db.DateTimeProperty(auto_now_add = True)
  created_by = db.UserProperty()
  
class Transaction(db.Model):
  created_at = db.DateTimeProperty(auto_now_add = True)
  description = db.TextProperty(default = '')

class Row(db.Model):
  transaction = db.ReferenceProperty(Transaction, collection_name = 'rows')
  account = db.ReferenceProperty(Account, collection_name = 'rows')
  created_at = db.DateTimeProperty(auto_now_add = True)
  delta = db.IntegerProperty()
  balance = db.IntegerProperty()
  debt = db.IntegerProperty()
  # level = db.IntegerProperty(default = NORMAL_LEVEL, choices = [ANONYMOUS_LEVEL, VIEWER_LEVEL, NORMAL_LEVEL, ADMIN_LEVEL, GOD_LEVEL])

# controllers

class FinishRequest(Exception):
  pass

class prolog(object):
  def __init__(decor, path_components = [], fetch = [], config_needed = True):
    decor.config_needed = config_needed
    decor.path_components = path_components
    decor.fetch = fetch
    pass

  def __call__(decor, original_func):
    def decoration(self, *args):
      try:
        return original_func(self, *args)
      except FinishRequest:
        pass
    decoration.__name__ = original_func.__name__
    decoration.__dict__ = original_func.__dict__
    decoration.__doc__  = original_func.__doc__
    return decoration

class BaseHandler(webapp.RequestHandler):
  def __init__(self):
    self.now = datetime.now()
    self.data = dict(now = self.now)
    
  def redirect_and_finish(self, url, flash = None):
    self.redirect(url)
    raise FinishRequest
    
  def render_and_finish(self, *path_components):
    self.response.out.write(template.render(os.path.join(template_path, *path_components), self.data))
    raise FinishRequest
    
  def access_denied(self, message = None, attemp_login = True):
    if attemp_login and self.user == None and self.request.method == 'GET':
      self.redirect_and_finish(users.create_login_url(self.request.uri))
    self.die(403, 'access_denied.html', message=message)

  def not_found(self, message = None):
    self.die(404, 'not_found.html', message=message)

  def invalid_request(self, message = None):
    self.die(400, 'invalid_request.html', message=message)
    
  def die(self, code, template, message = None):
    if message:
      logging.warning("%d: %s" % (code, message))
    self.error(code)
    self.data.update(message = message)
    self.render_and_finish('errors', template)
    
  def compute_balance_for(self, accounts):
    for account in accounts:
      rows = account.rows.order('-created_at').fetch(100)
      balance = None
      delta = 0
      debt = None
      for row in rows:
        if balance == None and row.balance != None:
          balance = row.balance
        if balance == None and row.delta != None:
          delta += row.delta
        if debt == None and row.debt != None:
          debt = row.debt
      if balance != None:
        balance += delta
      account.balance = balance / 100.0 if balance else None
      account.debt = debt / 100.0 if debt else None
    
class SettingsHandler(BaseHandler):
  
  @prolog()
  def get(self):
    self.data.update(accounts = Account.all().fetch(20))
    self.render_and_finish('settings.html')

class SettingsAddAccountHandler(BaseHandler):

  @prolog()
  def post(self):
    account = Account()
    account.name = self.request.get('name')
    account.put()
    self.redirect_and_finish('/settings')

class MainHandler(BaseHandler):

  @prolog()
  def get(self):
    transactions = Transaction.all().order('-created_at').fetch(20)
    for transaction in transactions:
      transaction.fetched_rows = transaction.rows.fetch(200)
    
    accounts = Account.all().order('name').fetch(20)
    self.compute_balance_for(accounts)
      
    self.data.update(accounts = accounts, transactions = transactions)
    self.render_and_finish('main.html')

class CreateTransactionHandler(BaseHandler):

  @prolog()
  def get(self):
    accounts = Account.all().order('name').fetch(20)
    self.compute_balance_for(accounts)
    self.data.update(accounts = accounts)
    self.render_and_finish('create.html')

  @prolog()
  def post(self):
    accounts = Account.all().order('name').fetch(20)
    
    rows = []
    for account in accounts:
      row = Row()
      row.account = account
      balance = self.request.get('%s_balance' % account.key())
      delta   = self.request.get('%s_delta' % account.key())
      debt    = self.request.get('%s_debt' % account.key())
      if balance != None and balance != '':
        row.balance = int(float(balance) * 100)
      if delta != None and delta != '':
        row.delta = int(float(delta) * 100)
      if debt != None and debt != '':
        row.debt = int(float(debt) * 100)
      if row.balance or row.delta or row.debt:
        rows.append(row)
      
    transaction = Transaction()
    transaction.description = self.request.get('description')
    transaction.put()
    
    for row in rows:
      row.transaction = transaction
      row.put()
        
    self.redirect_and_finish('/')

url_mapping = [
  ('/', MainHandler),
  ('/settings/create-account.do', SettingsAddAccountHandler),
  ('/add', CreateTransactionHandler),
  ('/settings', SettingsHandler),
]

def main():
  application = webapp.WSGIApplication(url_mapping, debug=True)
  wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
  main()
