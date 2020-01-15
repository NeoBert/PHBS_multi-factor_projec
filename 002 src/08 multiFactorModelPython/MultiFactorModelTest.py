# -*- coding: utf-8 -*-
"""
Created on Wed Jan  8 14:44:40 2020

@author: Evan
"""
import numpy as np 
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression, Lasso, Ridge
from tqdm import tqdm_notebook
from tqdm import tqdm
from collections import deque
from time import time
import os


class MultiFactorModelTest():
    def __init__(self, close, industryFactorCube, sytleFactorCube, alphaFactorCube, stockScreenTable, d_timeShift = 1 ):
        self.returnTable = (pd.DataFrame(close)-pd.DataFrame(close).shift(1))/pd.DataFrame(close).shift(1)
        self.shiftedReturnTable = self.returnTable.shift(-d_timeShift)
        self.industryFactorCube = industryFactorCube
        self.sytleFactorCube = sytleFactorCube
        self.alphaFactorCube = alphaFactorCube
        self.d_timeShift = d_timeShift
        self.stockScreenTable = stockScreenTable
        
    def getTimesliceData(self, timeslice, *args):
        output = []
        for cube in args:
            if np.ndim(cube)>2:
                output.append(cube[timeslice, :, :])
            else:
                output.append(cube[timeslice, :].reshape(-1,1))
        return(output)
    
    def setDTimeShift(self, d_timeShift):
        self.shiftedReturnTable = self.returnTable.shift(-d_timeShift)
        self.d_timeShift = d_timeShift
        
    def getMeanReturn(self, toWeightReturn):
        return(toWeightReturn.mean(0))
    
    def modelTest(self, toTestAlphaCube, noStyle, shiftedReturnTable = None, industryFactorCube = None, sytleFactorCube = None, stockScreenTable = None , getWeightExpectReturn = None,backTestDays = 200, T = 1 ,isLinearModel = True, useRidge = False):
        if not industryFactorCube:
            industryFactorCube = self.industryFactorCube
        if not sytleFactorCube:
            sytleFactorCube = self.sytleFactorCube
        if not getWeightExpectReturn:
            getWeightExpectReturn = self.getMeanReturn
        if not shiftedReturnTable:
            shiftedReturnTable = self.shiftedReturnTable
        if not stockScreenTable:
            stockScreenTable = self.stockScreenTable
            
        if noStyle:
            sytleFactorCube = np.zeros((toTestAlphaCube.shape[0], toTestAlphaCube.shape[1], 0))
        if np.ndim(toTestAlphaCube)==2:
            allXCount = industryFactorCube.shape[-1] +sytleFactorCube.shape[-1]+1
        else:
            allXCount = industryFactorCube.shape[-1] +sytleFactorCube.shape[-1] +toTestAlphaCube.shape[-1]
            
        factorReturnTable = np.zeros((shiftedReturnTable.shape[0], allXCount))
        validFactorTable = np.zeros((shiftedReturnTable.shape[0], allXCount))
        predictReturnTable = np.zeros(shiftedReturnTable.shape)
        modelIC = np.zeros(shiftedReturnTable.shape[0])
        modelQueue = deque(maxlen=T)
        
        for timeslice in tqdm(range(shiftedReturnTable.shape[0]-backTestDays, shiftedReturnTable.shape[0]-self.d_timeShift)):
    
#             tqdm.write("start process:"+str(timeslice))
            starttime= time()

            #slice each table using timeslice
            X_industry, X_style, X_alpha = self.getTimesliceData(timeslice,
                                                                 industryFactorCube,
                                                                 sytleFactorCube, 
                                                                 toTestAlphaCube)
            alphaCount = X_alpha.shape[-1]
            stockScrean = stockScreenTable[timeslice, :]           
            y_shiftedReturn = shiftedReturnTable.loc[timeslice]

            #mask to get valid datas(company):validToCal
            X_all = np.concatenate([X_industry, X_style, X_alpha], axis= 1)
            toMask = np.concatenate([np.array(y_shiftedReturn).reshape(-1, 1), X_all],axis = 1)
            finiteIndex = np.isfinite(toMask).all(axis = 1)
            validIndex = np.logical_and(finiteIndex,  stockScrean.astype(bool))
            validToCal = toMask[validIndex, :]
            
            # rank issue here
            if isLinearModel:
                X_toCheckRank = validToCal[:, 1:]
                validColumn = ~(X_toCheckRank==0).all(axis = 0)
                validFactorTable[timeslice, : ] = validColumn
                
                X = X_toCheckRank[:, validColumn]
            else:
                X = validToCal[:, 1:]
                validFactorTable[timeslice, : ] = 1
            y = validToCal[:, 0]

            # check if all the model is ready, if true, predict next day epsilon with previos models
            if len(modelQueue)==T:

                # predict with pass T days model, get mean of all predection
                toWeightReturn = np.zeros((T, shiftedReturnTable.shape[1]))
                for i, aModel in enumerate(modelQueue):
                    if isLinearModel:
                        epsilon = aModel.coef_[-alphaCount:].dot(X[:, -alphaCount:].T)
                        toWeightReturn[i, validIndex] = epsilon
                    else:
                        toWeightReturn[i, validIndex] = aModel.predict(X)
                        
                # get mean     
                predictReturn = getWeightExpectReturn(toWeightReturn)
                predictReturnTable[timeslice] = predictReturn

                #record the ic of today
                modelIC[timeslice] = np.corrcoef(predictReturn[validIndex], y)[0,1]

            # fit new model using today alpha exposure and next day's return
            # adjust for all kinds of models later
            if useRidge:
                model = Ridge(alpha = 1, fit_intercept=False)
            else:
                model = LinearRegression(fit_intercept=False)
            model.fit(X, y)
            modelQueue.append(model)

            # save the factor return(beta of the model)
            if isLinearModel:
                todayFReturn = model.coef_
                factorReturnTable[timeslice, validColumn] = todayFReturn
                
        #         return
        return(modelIC, predictReturnTable, factorReturnTable, validFactorTable)
        
    def multiFactorTest(self,  noStyle, doPlot = True, backTestDays = 200, T = 1, useRidge = True):
        toTestAlphaCube = self.alphaFactorCube
        modelIC, predictReturnTable, factorReturnTable, validFactorTable = self.modelTest(toTestAlphaCube, noStyle = noStyle, backTestDays = backTestDays, T = T, useRidge=useRidge)
        if doPlot:
            plt.figure(figsize = (15, 6))
            plt.title('IC of alpha model')
            plt.plot(modelIC[-backTestDays+1:-1],'-o', ms = 3)
            plt.hlines(0, 0, backTestDays)
            plt.hlines(modelIC[-backTestDays+1:-1].mean(), -1, 1)
            
        print("modelIC mean of alpha model ", ":", modelIC[-backTestDays+1:-1].mean())
        return(modelIC, predictReturnTable, factorReturnTable, validFactorTable)
    
    def singleFactorTest(self, indexToTest, noStyle, doPlot = True, backTestDays = 200, T = 1, useRidge=False):
        toTestAlphaCube = self.alphaFactorCube[:, :, indexToTest]
        modelIC, predictReturnTable, factorReturnTable, validFactorTable = self.modelTest(toTestAlphaCube, noStyle = noStyle, backTestDays = backTestDays, T = T, useRidge=useRidge)
        if doPlot:
            plt.figure(figsize = (15, 6))
            plt.title('IC of alpha number:'+str(indexToTest))
            plt.plot(modelIC[-backTestDays+1:-1],'-o', ms = 3)
            plt.hlines(0, 0, backTestDays)
            plt.hlines(modelIC[-backTestDays+1:-1].mean(), -1, 1)
            
        print("modelIC mean of alpha index ", indexToTest, ":", modelIC[-backTestDays+1:-1].mean())
        return(modelIC, predictReturnTable, factorReturnTable, validFactorTable)
    
    
    def singleFactorTestAll(self, noStyle, doPlot = True, backTestDays = 200, T = 1, useRidge=False, saveDir = './'):
        modelICs = {}
        predictReturnTables = {}
        factorReturnTables = {}
        alphaCount = self.alphaFactorCube.shape[-1]
        
        if doPlot:
            fig = plt.figure(figsize=(45, (alphaCount//3+1)*10))
            
        for i in tqdm(range(alphaCount)):
            modelIC, predictReturnTable, factorReturnTable, validFactorTable = self.singleFactorTest(i,noStyle = noStyle ,doPlot = False, backTestDays = backTestDays,T = T, useRidge=useRidge)
            modelICs.update({
                i:modelIC
            })
            predictReturnTables.update({
                i:predictReturnTable
            })
            factorReturnTables.update({
                i:factorReturnTables
            })
            if doPlot:
                plt.subplot(alphaCount//3+1, 3, i+1)
                plt.plot(modelIC[-backTestDays+1:-1],'-o', ms = 3)
                plt.title('IC of alpha number:'+str(i))
                plt.hlines(0, 0, backTestDays)
                
        if doPlot:
            saveFile = os.path.join(saveDir,"allSingleNormalIC.png" )
            plt.savefig(saveFile)
                
        return(modelICs, predictReturnTables, factorReturnTables)
        
        
        
            
        
        


        