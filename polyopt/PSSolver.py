#!/usr/bin/python3

from .SDPSolver import SDPSolver
from .polalg import Polalg
from .linalg import Linalg
#from math import ceil
#from scipy.misc import comb
#from numpy.random import uniform
#from numpy.linalg import *
import sys
import copy
import signal
import logging
import numpy as np

class PSSolver:
  """
  Class providing PS (Polynomial Systems) solver.

  Solves problem in this form:
    f1(x) = 0
    ...
    fm(x) = 0

  by Pavel Trutman, pavel.tutman@cvut.cz
  """

  # some constants
  eps = 1e-9
  SDPTimeout = 60
  rankDecayThreshold = 1e-6
  rankZeroThreshold = 1e-3
  numericalFailsLimit = 5


  def __init__(self, I):
    """
    Initialization of the PS problem.

    Args:
      I (list of polynomials): list of polynomials f1(x), ..., fm(x)
    """

    # save the ideal
    self.I = I

    # get number of variables and the maximal degree of polynomials in I
    D = 0
    IDegs = []
    for h in I:
      deg = 0
      for monomial in h:
        if sum(monomial) > deg:
          deg = sum(monomial)
      if deg > D:
        D = deg
        n = len(monomial)
      IDegs.append(deg)
    self.n = n
    self.d = int(np.ceil(D/2))
    self.D = D
    self.IDegs = IDegs

    # disable output
    logging.basicConfig(stream = sys.stdout, format = '%(message)s')
    self.logStdout = logging.getLogger()

    # prepare H for first iteration
    self.t = self.D
    self.monAll = Polalg.generateVariablesUpDegree(self.t, self.n, reverse = True)
    HRows = sum([Polalg.numVariablesUpDegree(self.t - deg, self.n) for deg in self.IDegs])
    self.H = np.zeros((HRows, len(self.monAll)))
    j = 0
    for i in range(0, len(self.I)):
      upMons = Polalg.generateVariablesUpDegree(self.t - self.IDegs[i], self.n, reverse = True)
      for monomial in upMons:
        self.H[j, :] = self.multiplyPolMon(self.I[i], monomial)
        j += 1

    # set some class variables
    self.finished = False
    self.solved = False


  def solve(self):
    """
    Solve the problem.

    Returns:
      array: solution to the problem
    """

    done = False
    while not done:
      oldT = self.t
      done = self.iteration()
      if oldT == self.t:
        numericalFails += 1
        if numericalFails >= self.numericalFailsLimit:
          return np.empty((0, 0))
      else:
        numericalFails = 0
    self.computeSolution()

    return self.solution


  def iteration(self, permutation = None):
    """
    Execute next iteration of the moment method algorithm.

    Args:
      permutation(list): some permutation of columns

    Returns:
      bool: True:  finished, no next iteration required
            False: not finished, run next iteration
    """

    # check if finished
    if self.finished:
      return True

    # run the iteration
    tHalfFloor = int(np.floor(self.t/2))
    numMonUptHalfFloor = Polalg.numVariablesUpDegree(tHalfFloor, self.n)
    print('t = ', self.t)

    # projection
    monAbsIdx = len(self.monAll) - 1
    # REMOVE
    #yAll = np.empty((len(monAll), numRepetitions))
    #MAll = np.empty((numMonUptHalfFloor, numMonUptHalfFloor, numRepetitions))
    #eAll = np.empty((numMonUptHalfFloor, numRepetitions))
    #
    AOrig = [np.zeros((numMonUptHalfFloor, numMonUptHalfFloor)) for _ in range(len(self.monAll))]
    for i in range(0, numMonUptHalfFloor):
      for j in range(0, numMonUptHalfFloor):
        monomial = tuple(map(sum, zip(self.monAll[-i -1], self.monAll[-j -1])))
        idx = self.monAll.index(monomial)
        AOrig[idx][i, j] += 1
    # REMOVE
    #repetition = 0
    #repetitionLimit = 0
    #while repetition < numRepetitions:
      #repetitionLimit += 1
      #if repetitionLimit > numRepetitionsLimit:
        #return array(())
    #
    if permutation is None:
      varsPermuted = np.random.permutation(monAbsIdx).tolist()
      varsPermuted.append(monAbsIdx)
    else:
      varsPermuted = permutation
    Hrref, varsToReplace = Linalg.rref(self.H[:, varsPermuted], self.eps)
    varsToReplaceOrig = varsToReplace
    varsToReplace = [varsPermuted[i] for i in varsToReplace]
    varsToKeep = [var for var in varsPermuted if var not in varsToReplace]
    varsToKeepPermuted = [varsPermuted.index(var) for var in varsToKeep]
    if monAbsIdx not in varsToKeep:
      varsToKeep.append(monAbsIdx)
    varsToSolve = list(reversed(varsToKeep))
    A = [np.zeros((numMonUptHalfFloor, numMonUptHalfFloor)) for _ in varsToSolve]
    for i in range(0, numMonUptHalfFloor):
      for j in range(0, numMonUptHalfFloor):
        monomial = tuple(map(sum, zip(self.monAll[-i -1], self.monAll[-j -1])))
        idx = self.monAll.index(monomial)
        if idx in varsToKeep:
          A[varsToSolve.index(idx)][i, j] += 1
        else:
          row = np.nonzero(Hrref[:, varsPermuted.index(idx)])[0][0]
          replaceRow = -Hrref[row, varsToKeepPermuted]
          for var, value in zip(varsToKeep, replaceRow):
            A[varsToSolve.index(var)][i, j] += value

    # remove zero matrices
    ANew = []
    varsToSolveNew = []
    for i in range(len(varsToSolve)):
      if np.count_nonzero(A[i]):
        ANew.append(A[i])
        varsToSolveNew.append(varsToSolve[i])
    A = ANew
    varsToSolve = varsToSolveNew

    # eigenvalues for y = 0
    e = np.linalg.eigvals(A[0])
    e.sort()

    # get feasible point
    if any(e <= 0):
      # SDP problem B with tau
      tau = -min(e).real + 1
      Atau = np.eye(A[0].shape[0])
      B = copy.copy(A)
      B.append(Atau)
      Btau = [np.zeros((1, 1)) for _ in varsToSolve]
      Btau.append(np.array([[1]]))
      BtauMax = [np.zeros((1, 1)) for _ in varsToSolve]
      BtauMax.append(np.array([[-1]]))
      BtauMax[0] = np.array([[tau + 1]])
      print('tau max:', tau + 1)
      SDP = SDPSolver(np.concatenate((np.zeros((len(varsToSolve) - 1, 1)), [[1]]), axis=0), [B, Btau, BtauMax])
      SDP.setPrintOutput(False)
      SDP.bound(max([1e6, 1e3*tau]))
      SDP.eps = self.eps

      # run SDP solver with error handling
      numInstability = False
      with np.errstate(invalid='raise'):
        signal.signal(signal.SIGALRM, self.signalAlarmHandler)
        signal.alarm(self.SDPTimeout)
        try:
          y = SDP.solve(np.concatenate((np.zeros((len(varsToSolve) - 1, 1)), [[tau]]), axis=0), SDP.dampedNewton)
          signal.alarm(0)
        except(FloatingPointError, np.linalg.linalg.LinAlgError, self.AlarmError) as e:
          print(e)
          numInstability = True
      # check zero tau
      if not numInstability and y[-1] > self.eps:
        numInstability = True
        print('Tau no zero. tau = ', y[-1])
      if SDP.solved:
        if any(np.array(SDP.eigenvalues('original')) < -self.eps):
          numInstability = True
          print('Large negative eigenvalues!')
        else:
          y = y[:-1]
    else:
      # find analytics center
      SDP = polyopt.SDPSolver(zeros((len(varsToSolve) - 1, 1)), [A])
      SDP.setPrintOutput(False)
      SDP.bound(1e3)
      SDP.eps = self.eps
      y = SDP.dampedNewton(zeros((len(varsToSolve) - 1, 1)))

    # check results of the SDP
    if not numInstability:
      # project back
      varsToSolvePermuted = [varsPermuted.index(var) for var in varsToSolve]
      yAbs = np.concatenate(([[1]], y))
      yOrig = np.empty((len(self.monAll), 1))*np.nan
      for var in range(0, len(self.monAll)):
        if var == monAbsIdx:
          yOrig[var] = 1
        elif var in varsToSolve:
          yOrig[var] = y[varsToSolve.index(var)-1]
        elif var in varsToReplace:
          row = np.nonzero(Hrref[:, varsPermuted.index(var)])[0][0]
          replaceRow = -Hrref[row, varsToSolvePermuted]
          yOrig[var] = np.dot(replaceRow, yAbs)

      M = np.sum([Ai*yi for Ai, yi in zip(AOrig, yOrig) if not np.isnan(yi)], axis=0)
      e = np.linalg.eigvals(M)
      if any(e < -self.eps):
        print('Large negative eigenvalues after projecting back!')
        return False
    else:
      return False

    sRanks = [None]*(tHalfFloor + 1)
    done = False
    # check condition (2.14)
    for s in range(self.D, tHalfFloor + 1):
      if sRanks[s] is None:
        sRanks[s] = self.rankOfOrder(M, s)
      if sRanks[s - 1] is None:
        sRanks[s - 1] = self.rankOfOrder(M, s - 1)
      if sRanks[s] == sRanks[s - 1]:
        numSolutions = sRanks[s]
        done = True
        break
    # check condition (2.15)
    if not done:
      for s in range(self.d, tHalfFloor + 1):
        if sRanks[s] is None:
          sRanks[s] = self.rankOfOrder(M, s)
        if sRanks[s - self.d] is None:
          sRanks[s - self.d] = self.rankOfOrder(M, s - self.d)
        if sRanks[s] == sRanks[s - self.d]:
          numSolutions = sRanks[s]
          done = True
          break

    # print ranks for s
    for s in range(tHalfFloor + 1):
      if sRanks[s] is None:
        sRanks[s] = self.rankOfOrder(M, s)
      sNumMons = Polalg.numVariablesUpDegree(s, self.n)
      _, sValues, _ = np.linalg.svd(M[0:sNumMons, 0:sNumMons])
      print('s = {}, rank = {}'.format(s, sRanks[s]))
      print(sValues)
      print()

    if done:
      # save results
      self.finished = True
      self.M = M
      self.numSolutions = numSolutions
      self.sRanks = sRanks

      # finished, compute the solution
      return True

    # prepare for next iteration
    self.t += 1
    self.monAll[:0] = Polalg.generateVariablesDegree(self.t, self.n)
    HRowsAdd = sum([Polalg.numVariablesDegree(self.t - deg, self.n) for deg in self.IDegs])
    HAdd = np.zeros((HRowsAdd, len(self.monAll)))
    j = 0
    for i in range(0, len(self.I)):
      upMons = Polalg.generateVariablesDegree(self.t - self.IDegs[i], self.n)
      for monomial in upMons:
        HAdd[j, :] = self.multiplyPolMon(self.I[i], monomial)
        j += 1
    self.H = np.concatenate((np.zeros((self.H.shape[0], len(self.monAll) - self.H.shape[1])), self.H), axis=1)
    self.H = np.concatenate((self.H, HAdd), axis=0)

    # next iteration
    return False


  def computeSolution(self):
    """
    Computes solution, when the the iterations are finished.

    Returns:
      None

    Throws:
      ValueError: when the iterations are not finished yet
    """

    # check that it is finished
    if not self.finished:
      raise ValueError('The iterations are not computed, so the solution can not be evaluated.')

    # compute the solution
    for i, r in zip(range(len(self.sRanks)), self.sRanks):
      if r == self.numSolutions:
        s = i + 1
        break
    M = self.M[0:Polalg.numVariablesUpDegree(s, self.n), 0:Polalg.numVariablesUpDegree(s, self.n)]

    # kernel and the monomial basis
    U, S, V = np.linalg.svd(M)
    S[self.numSolutions:] = 0
    Bidx = Linalg.independendentColumns(M, self.numSolutions, self.eps)
    MrKer = V[self.numSolutions:, :]
    nonBidx = [e for e in range(M.shape[0]) if e not in Bidx]
    sidx = sorted(range(len(nonBidx + Bidx)), key=(nonBidx + Bidx).__getitem__) # get indices of sorted list
    MrKer = Linalg.rref(MrKer[:, nonBidx + Bidx])[0][:, sidx]

    # multiplication matrix
    X = np.zeros((self.numSolutions, self.numSolutions))
    var = (1, ) + (0, )*(self.n - 1)
    for row, monIdx in zip(range(self.numSolutions), Bidx):
      mon = self.monAll[len(self.monAll) - monIdx - 1]
      monNew = tuple(map(sum, zip(mon, var)))
      idx = len(self.monAll) - self.monAll.index(monNew) - 1
      if idx in Bidx:
        X[row, idx] = 1
      else:
        X[row, :] = -MrKer[MrKer[:, idx] == 1, Bidx]
    e, V = np.linalg.eig(X)
    print('X:', X)
    V = V/V[0, :]
    print('V')
    print(V)

    # compute the rest of the variables
    sol = np.empty((self.numSolutions, self.n))*np.nan
    for i in range(self.n):
      col = self.n - i - 1
      if i + 1 in Bidx:
        sol[:, col] = V[Bidx.index(i + 1), :]
      else:
        sol[:, col] = -MrKer[MrKer[:, i+1] == 1, Bidx].dot(V)
    print(sol)

    # save the solution
    self.solution = sol
    self.solved = True


  def multiplyPolMon(self, polynomial, monomial):
    """
    Multiplies polynomial with monomial and returns it as a matrix.

    Args:
      polynomial (dict): a polynomial
      monomial (tuple): a monomial

    Returns:
      array: matrix representation of the resulting polynomial
    """

    newPoly = np.zeros((1, len(self.monAll)))
    for mon in polynomial:
      newMon = tuple(map(sum, zip(mon, monomial)))
      newPoly[0, self.monAll.index(newMon)] = polynomial[mon]
    return newPoly


  def rankOfOrder(self, matrix, order):
    """
    Computes rank of the submatrix with given order of given matrix.

    Args:
      matrix (array): matrix to analyze
      order (int): order of the submatrix

    Returns:
      int: rank of the submatrix
    """

    numMons = Polalg.numVariablesUpDegree(order, self.n)
    return Linalg.rank(matrix[0:numMons, 0:numMons], self.rankDecayThreshold, self.rankZeroThreshold)


  class AlarmError(Exception):
    """
    Timeout exception.
    """

    pass


  def signalAlarmHandler(signum, frame):
    """
    Handler to the alarm signal.
    """

    raise AlarmError('Timeout expired.')